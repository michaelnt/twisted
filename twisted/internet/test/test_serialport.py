# copyright (c) 2010 Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Tests for L{twisted.internet.serialport}.
"""


try:
    from serial import SerialException
except ImportError, e:
    skip = "serial support unavailable (%s)" % (e,)
else:
    from twisted.internet.serialport import SerialPort

import os
import socket
import sys
from twisted.internet.interfaces import IReactorFDSet, IReactorWin32Events
from twisted.internet.defer import Deferred
from twisted.internet.test.reactormixins import ReactorBuilder
from twisted.trial.unittest import SkipTest
from twisted.test.test_tcp import ConnectionLostNotifyingProtocol
from twisted.python.runtime import platformType
from twisted.internet.protocol import Protocol, ServerFactory
from twisted.protocols.wire import Echo
from twisted.python import log

import serial


class _MockPosixSerial(serial.Serial):
    """
    An L{serial.Serial} class that uses a pty to mock a serial port on Posix systems.
    """
    def open(self, *args, **kwargs):
        self.master, self.slave = os.openpty()
        self.fd = self.master


class _MockWindowsSerial(object):
    """
    A select()able serial device, acting as a transport.
    """
    def __init__(self, deviceNameOrPortNumber, **kwargs):
        self.hComPort = deviceNameOrPortNumber
    
    def flushInput(self):
        pass

    def flushOutput(self):
        pass

    def close(self):
        import win32api
        win32api.CloseHandle(self.hComPort)


class _MockPosixSerialPort(SerialPort):
    serialFactory = _MockPosixSerial


class _MockWindowsSerialPort(SerialPort):
    serialFactory = _MockWindowsSerial


class _MockWindowsEchoPort(SerialPort):

    serialFactory = _MockWindowsSerial

    def slaveConnected(self):
        log.msg('Slave Connected')
        import win32file, win32event, win32pipe
        self._overlappedRead = win32file.OVERLAPPED()
        self._overlappedRead.hEvent = win32event.CreateEvent(None, 1, 0, None)
        self.reactor.addEvent(self._overlappedRead.hEvent, self, 'serialReadEvent')
        win32event.SetEvent(self._overlappedRead.hEvent)


    def startReading(self):
        log.msg('startReading')
        import win32file, win32event, win32pipe
        self._overlapped = win32file.OVERLAPPED()
        self._overlapped.hEvent = win32event.CreateEvent(None, 1, 1, None)
        self.reactor.addEvent(self._overlapped.hEvent, self, 'slaveConnected')
        rc = win32pipe.ConnectNamedPipe(self._serial.hComPort, self._overlapped)

        import winerror
        if rc == winerror.ERROR_IO_PENDING:
            log.msg('ConnectNamedPipe returned ERROR_IO_PENDING')
        elif rc == winerror.ERROR_PIPE_CONNECTED:
            log.msg('ConnectNamedPipe returned PIPE_CONNECTED')
            self.slaveConnected()
        else:
            log.msg('ConnectNamedPipe returned unexpected code %d' % rc)

        

class AccumulatingProtocol(Protocol):
    """
    Fire a C{Deferred} with the  L{IProtocol.dataReceived} is called
    """

    def __init__(self, deferred, expectedNumberOfReads):
        self.deferred = deferred
        self.dataReceivedList = ''
        self.expectedNumberOfReads = expectedNumberOfReads


    def dataReceived(self, data):
        self.dataReceivedList += data
        log.msg('dataReceived = %r' % data)
        if len(self.dataReceivedList) >= self.expectedNumberOfReads:
            self.deferred.callback(self.dataReceivedList)



class SerialPortTests(object):
    def testLoseConnection(self):
        """
        The serial port transport implementation of C{loseConnection}
        causes the serial port to be closed and the protocol's
        C{connectionLost} method to be called with a L{Failure}
        wrapping L{ConnectionDone}.
        """
        onConnectionLost = Deferred()
        protocol = ConnectionLostNotifyingProtocol(onConnectionLost)
        port = self.serialFactory(protocol, self.reactor)

        def cbConnLost(ignored):
            self.reactor.stop()
        onConnectionLost.addCallback(cbConnLost)

        port.loseConnection()
        
        self.runReactor(self.reactor)
    testLoseConnection.timeout = 2


    def testLoopback(self):
        """
        L{SerialPort.writeSomeData} should write data to a ptty. Data
        written to this ptty should cause L{IProtocol.dataReceived} to
        be called with this data.
        """
        d = Deferred()
        aMessage = "Send A String"
        protocol = AccumulatingProtocol(d, len(aMessage))
        serial = self.serialFactory(protocol, self.reactor)
        serial.write(aMessage)

        def check(data):
            log.msg('check %s' % data)
            self.assertEquals(data, "Send A String")
            self.reactor.stop()
        d.addCallbacks(check, check)

        self.runReactor(self.reactor)
    testLoopback.timeout=2


    def testMultipleWrites(self):
        """
        L{SerialPort.writeSomeData} should write data to a ptty. Data
        written to this ptty should cause L{IProtocol.dataReceived} to
        be called with this data.
        """
        d = Deferred()
        protocol = AccumulatingProtocol(d, len('OneTwoThree'))
        serial = self.serialFactory(protocol, self.reactor)
        serial.write("One")
        serial.write("Two")
        serial.write("Three")

        def check(data):
            self.assertEquals(data, "OneTwoThree")
            self.reactor.stop()
        d.addCallbacks(check, check)

        self.runReactor(self.reactor)
    testMultipleWrites.timeout=2



class MockSerialPortTestsBuilder(ReactorBuilder, SerialPortTests):
    """
    Builder defining tests for L{twisted.internet.serialport}.

    If the environment variable C{TRIALSERIALPORT} is set, tests will
    use a real serial port at that address. This serial port should
    echo transmitted data, by connecting a wire from the Tx to the Rx
    pin of a serial connector.

    Otherwise a L{MockSerialPort} port will be used.    
    """
    def setUp(self):
        self.reactor = self.buildReactor()

        if platformType == "win32" and IReactorWin32Events.providedBy(self.reactor):
            pass
        elif platformType != "win32" and IReactorFDSet.providedBy(self.reactor):
            pass
        else:
            raise SkipTest(
                "Cannot use SerialPort without IReactorFDSet or "
                "IReactorWin32Events")


    def _serial_unix(self, protocol, reactor, **kwargs):
        """
        Use a unix socket to connect the L{MockSerialPort} to the L{Echo} protocol.

        The client connects to the socket before the server has been
        started, as the reactor isn't running yet. For this reason a
        TCP socket cannot be used.

        It would also be possible to implement this using os.opentty()
        """
        filename = self.mktemp()
        f = ServerFactory()
        f.protocol = Echo
        unixPort = self.reactor.listenUNIX(filename, f)
        self.addCleanup(unixPort.stopListening)

        unixSocket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(unixSocket.close)
        unixSocket.connect(filename)
    
        return _MockPosixSerialPort(protocol, unixSocket.fileno(), self.reactor)


    def _serial_win(self, protocol, reactor, **kwargs):
        """
        Use a named pipe to allow bidirection I/O over a file like
        objects that should be supported by the L{IReactorWin32Events}
        interface.

        http://msdn.microsoft.com/en-us/library/aa365603(v=vs.85).aspx

        """
        import win32event, win32pipe, win32file, win32api, winerror

        pipeName = r"\\.\pipe\serialport"
        self.master = win32pipe.CreateNamedPipe(
            pipeName, 
            win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED,  # Open Mode
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_NOWAIT,         # Pipe Mode
            1,                             # Max Instances
            6536,                          # OutBufferSize
            6536,                          # InBufferSize
            1,                             # DefaultTimeOut
            None                           # Security Attributes
            )

        self.slave1 = win32file.CreateFile(
            pipeName,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
            None,
            win32file.OPEN_EXISTING,
            win32file.FILE_FLAG_OVERLAPPED | win32file.FILE_ATTRIBUTE_NORMAL,
            None)
        
        serialPort = _MockWindowsSerialPort(protocol, self.slave1, self.reactor)

        pecho = Echo()
        _MockWindowsEchoPort(pecho, self.master, reactor)
        self.addCleanup(win32api.CloseHandle, self.master)
        self.addCleanup(win32api.CloseHandle, self.slave1)
        return serialPort


    def serialFactory(self, protocol, reactor, **kwargs):
        if os.name == "posix":
            return self._serial_unix(protocol, reactor, **kwargs)
        elif sys.platform == "win32":
            return self._serial_win(protocol, reactor, **kwargs)



class EchoSerialPortTestsBuilder(ReactorBuilder, SerialPortTests):
    """
    """
    def setUp(self):
        if not os.getenv("TRIALSERIALPORT"):
            raise SkipTest("environment variable TRIALSERIALPORT not set")
 
        self.reactor = self.buildReactor()

        if platformType == "win32" and IReactorWin32Events.providedBy(self.reactor):
            pass
        elif platformType != "win32" and IReactorFDSet.providedBy(self.reactor):
            pass
        else:
            raise SkipTest(
                "Cannot use SerialPort without IReactorFDSet or "
                "IReactorWin32Events")


    def tearDown(self):
        self.port.loseConnection()


    def serialFactory(self, protocol, reactor, **kwargs):
        deviceNameOrPortNumber = os.getenv("TRIALSERIALPORT")
        self.port = SerialPort(protocol, deviceNameOrPortNumber, reactor, **kwargs)
        return self.port



globals().update(MockSerialPortTestsBuilder.makeTestCaseClasses())
globals().update(EchoSerialPortTestsBuilder.makeTestCaseClasses())
