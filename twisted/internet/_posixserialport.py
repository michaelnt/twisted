# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Serial Port Protocol
"""

# dependent on pyserial ( http://pyserial.sf.net/ )
# only tested w/ 1.18 (5 Dec 2002)
import serial
from serial import EIGHTBITS, PARITY_NONE, STOPBITS_ONE

# Gross sibling Twisted import
from serialport import BaseSerialPort

# twisted imports
from twisted.internet import abstract, fdesc

class SerialPort(BaseSerialPort, abstract.FileDescriptor):
    """
    A select()able serial device, acting as a transport.
    """

    connected = 1
    serialFactory = serial.Serial

    def __init__(self, protocol, deviceNameOrPortNumber, reactor, 
                 baudrate=9600, bytesize=EIGHTBITS, parity=PARITY_NONE,
                 stopbits=STOPBITS_ONE, timeout=0, xonxoff=0, rtscts=0):

        abstract.FileDescriptor.__init__(self, reactor)
        self._serial = self.serialFactory(deviceNameOrPortNumber, baudrate=baudrate,
                                        bytesize=bytesize, parity=parity,
                                        stopbits=stopbits, timeout=timeout, 
                                        xonxoff=xonxoff, rtscts=rtscts)
        self.reactor = reactor
        self.flushInput()
        self.flushOutput()
        self.protocol = protocol
        self.protocol.makeConnection(self)
        self.startReading()


    def fileno(self):
        return self._serial.fd


    def writeSomeData(self, data):
        """
        Write some data to the serial device.
        """
        return fdesc.writeToFD(self.fileno(), data)


    def doRead(self):
        """
        Some data's readable from serial device.
        """
        return fdesc.readFromFD(self.fileno(), self.protocol.dataReceived)


    def connectionLost(self, reason):
        abstract.FileDescriptor.connectionLost(self, reason)
        # Running the close first make this easier to test
        self._serial.close()
        self.protocol.connectionLost(reason)
