# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.


"""
Serial port support for Windows.

Requires PySerial and win32all, and needs to be used with win32event
reactor.
"""

# system imports
import os
import serial
from serial import PARITY_NONE, PARITY_EVEN, PARITY_ODD
from serial import STOPBITS_ONE, STOPBITS_TWO
from serial import FIVEBITS, SIXBITS, SEVENBITS, EIGHTBITS
import pywintypes

# twisted imports
from twisted.protocols import basic
from twisted.internet import abstract, main
from twisted.python import log, failure

# sibling imports
from serialport import BaseSerialPort
import win32event, win32pipe, win32file, win32api, winerror

READBUF_SIZE = 1204



class SerialPort(BaseSerialPort, abstract.FileDescriptor):
    """
    A non blocking (overlapped) interface for reading and writing to a
    win32 file handle. 
    
    Requires a reactor that implements L{IReactorWin32Events}.
    """

    connected = 1
    SerialClass = serial.Serial

    def __init__(self, protocol, deviceNameOrPortNumber, reactor, 
        baudrate = 9600, bytesize = EIGHTBITS, parity = PARITY_NONE,
        stopbits = STOPBITS_ONE, xonxoff = 0, rtscts = 0):
        abstract.FileDescriptor.__init__(self, reactor)

        self._serial = self.SerialClass(deviceNameOrPortNumber, baudrate=baudrate,
                                     bytesize=bytesize, parity=parity,
                                     stopbits=stopbits, timeout=None,
                                     xonxoff=xonxoff, rtscts=rtscts)
        self.flushInput()
        self.flushOutput()
        self.outQueue = []
        self.writeInProgress = False

        self.protocol = protocol
        self.protocol.makeConnection(self)
        self.startReading()
        self.startWriting()


    def startReading(self):
        """
        Create and issue an overlapped Read
        """
        self._overlappedRead = win32file.OVERLAPPED()
        self._overlappedRead.hEvent = win32event.CreateEvent(None, 1, 0, None)
        self.reactor.addEvent(self._overlappedRead.hEvent, self, 'serialReadEvent')

        # Ask for a read and fire the event once the read has occured
        rc, self.read_buf = win32file.ReadFile(self._serial.hComPort,
                                               win32file.AllocateReadBuffer(READBUF_SIZE),
                                               self._overlappedRead)


    def startWriting(self):
        """
        Create the overlapped Write Structures.
        """
        self._overlappedWrite = win32file.OVERLAPPED()
        self._overlappedWrite.hEvent = win32event.CreateEvent(None, 0, 0, None)
        self.reactor.addEvent(self._overlappedWrite.hEvent, self, 'doWrite')


    def serialReadEvent(self):
        """
        A read event has occured.
        """
        try:
            n = win32file.GetOverlappedResult(self._serial.hComPort, self._overlappedRead, 0)
        except pywintypes.error as e:
            self.connectionLost(e)
            return

        if n > 0:
            # Read the data from the buffer before the buffer is reset.
            data = str(self.read_buf[:n])  
            self.protocol.dataReceived(data)

        # The read operation has completed and n bytes have been read 
        # into the buffer. Set up the next read operation
        win32event.ResetEvent(self._overlappedRead.hEvent)
        try:
            rc, self.read_buf = win32file.ReadFile(
                self._serial.hComPort,
                win32file.AllocateReadBuffer(READBUF_SIZE),
                self._overlappedRead)
        except Exception as e:
            self.connectionLost(e)


    def write(self, data):
        '''
        If a write is still in progress then queue the data otherwrite
        write data to the File Descriptor.
        '''
        if self.writeInProgress:
            self.outQueue.append(data)
        else:
            self._pendingData = data
            self.writeInProgress = 1
            # data must not be garbage collected until it has been written
            win32file.WriteFile(self._serial.hComPort, 
                                self._pendingData, 
                                self._overlappedWrite)

        
    def doWrite(self):
        '''
        A write has occured.
        Write any pending data and handle any errors

        return True if file closed.
        '''
        n = win32file.GetOverlappedResult(self._serial.hComPort, 
                                          self._overlappedWrite, 
                                          1)
        if n==0:
            # Write Failed
            return True
        else:
            self.writeInProgress = False
            if len(self.outQueue)> 0:
                self.writeSomeData(self.outQueue.pop())

            return False


    def connectionLost(self, reason):
        self.reactor.removeEvent(self._overlappedRead.hEvent)
        self.reactor.removeEvent(self._overlappedWrite.hEvent)
        abstract.FileDescriptor.connectionLost(self, reason)
        # Running the close first make this easier to test
        self._serial.close()
        self.protocol.connectionLost(reason)
