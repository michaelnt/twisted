# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.


"""Qt demo.

Fetch a URL's contents.
"""

import sys, urlparse

from PySide.QtCore import QSocketNotifier, QObject, SIGNAL, QTimer, QCoreApplication
from PySide.QtCore import QEventLoop
from PySide import QtGui
from PySide.QtWebKit import QWebView

from twisted.internet import protocol

app = QtGui.QApplication(sys.argv)
from twisted.internet import qtreactor
qtreactor.install()

# The reactor must be installed before this import
from twisted.web import http


class TwistzillaClient(http.HTTPClient):
    def __init__(self, web, urls):
        self.urls = urls
        self.web = web

    def connectionMade(self):
        print 'Connected.'

        self.sendCommand('GET', self.urls[2])
        self.sendHeader('Host', '%s:%d' % (self.urls[0], self.urls[1]) )
        self.sendHeader('User-Agent', 'Twistzilla')
        self.endHeaders()

    def handleResponse(self, data):
        print 'Got response.'
        self.web.setHtml(data)



class TwistzillaWindow(QtGui.QMainWindow):
    def __init__(self, *args):
        QtGui.QMainWindow.__init__(self, *args)

        self.centralwidget = QtGui.QWidget(self)

        vbox = QtGui.QVBoxLayout(self.centralwidget)

        hbox = QtGui.QHBoxLayout()
        label = QtGui.QLabel("Address: ")
        self.line  = QtGui.QLineEdit("http://www.twistedmatrix.com/")
        self.connect(self.line, SIGNAL('returnPressed()'), self.fetchURL)
        hbox.addWidget(label)
        hbox.addWidget(self.line)

        self.web = QWebView()

        vbox.addLayout(hbox)
        vbox.addWidget(self.web)
        vbox.setMargin(2)
        vbox.setSpacing(3)

        self.setCentralWidget(self.centralwidget)


    def fetchURL(self):
        u = urlparse.urlparse(str(self.line.text()))

        pos = u[1].find(':')

        if pos == -1:
            host, port = u[1], 80
        else:
            host, port = u[1][:pos], int(u[1][pos+1:])

        if u[2] == '':
            file = '/'
        else:
            file = u[2]

        print 'Connecting to.'
        from twisted.internet import reactor
        protocol.ClientCreator(reactor, TwistzillaClient, self.web, (host, port, file)).connectTCP(host, port)


def main():
    """Run application."""
    win = TwistzillaWindow()
    win.show()

    from twisted.internet import reactor
    reactor.run()

if __name__ == '__main__':
    main()
