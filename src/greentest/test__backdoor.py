from __future__ import print_function
import greentest
import gevent
from gevent import socket
from gevent import backdoor

def read_until(conn, postfix):
    read = b''
    if not isinstance(postfix, bytes):
        postfix = postfix.encode('utf-8')
    while not read.endswith(postfix):
        result = conn.recv(1)
        if not result:
            raise AssertionError('Connection ended before %r. Data read:\n%r' % (postfix, read))
        read += result

    return read if isinstance(read, str) else read.decode('utf-8')

def readline(conn):
    with conn.makefile() as f:
        return f.readline()

class Test(greentest.TestCase):

    __timeout__ = 10

    _server = None

    def tearDown(self):
        self._server.stop()
        self._server = None
        gevent.sleep() # let spawned greenlets die
        super(Test, self).tearDown()

    def _make_server(self, *args, **kwargs):
        self._server = backdoor.BackdoorServer(('127.0.0.1', 0), *args, **kwargs)
        self._close_on_teardown(self._server.stop)
        self._server.start()

    def _create_connection(self):
        conn = socket.socket()
        self._close_on_teardown(conn)
        conn.connect(('127.0.0.1', self._server.server_port))
        return conn

    def _close(self, conn):
        conn.sendall(b'quit()\r\n')
        line = readline(conn)
        self.assertEqual(line, '')
        conn.close()
        self.close_on_teardown.remove(conn)

    def test_multi(self):
        self._make_server()

        def connect():
            conn = self._create_connection()
            read_until(conn, b'>>> ')
            conn.sendall(b'2+2\r\n')
            line = readline(conn)
            self.assertEqual(line.strip(), '4', repr(line))
            self._close(conn)

        jobs = [gevent.spawn(connect) for _ in range(10)]
        done = gevent.joinall(jobs, raise_error=True)

        self.assertEqual(len(done), len(jobs), done)


    def test_quit(self):
        self._make_server()
        conn = self._create_connection()
        read_until(conn, b'>>> ')
        self._close(conn)

    def test_sys_exit(self):
        self._make_server()
        conn = self._create_connection()
        read_until(conn, b'>>> ')
        conn.sendall(b'import sys; sys.exit(0)\r\n')
        line = readline(conn)
        self.assertEqual(line, '')

    def test_banner(self):
        banner = "Welcome stranger!" # native string
        self._make_server(banner=banner)
        conn = self._create_connection()
        response = read_until(conn, b'>>> ')
        self.assertEqual(response[:len(banner)], banner, response)

        self._close(conn)

    def test_builtins(self):
        self._make_server()
        conn = self._create_connection()
        read_until(conn, b'>>> ')
        conn.sendall(b'locals()["__builtins__"]\r\n')
        response = read_until(conn, '>>> ')
        self.assertTrue(len(response) < 300, msg="locals() unusable: %s..." % response)

        self._close(conn)

    def test_switch_exc(self):
        from gevent.queue import Queue, Empty

        def bad():
            q = Queue()
            print('switching out, then throwing in')
            try:
                q.get(block=True, timeout=0.1)
            except Empty:
                print("Got Empty")
            print('switching out')
            gevent.sleep(0.1)
            print('switched in')

        self._make_server(locals={'bad': bad})
        conn = self._create_connection()
        read_until(conn, b'>>> ')
        conn.sendall(b'bad()\r\n')
        response = read_until(conn, '>>> ')
        response = response.replace('\r\n', '\n')
        self.assertEqual('switching out, then throwing in\nGot Empty\nswitching out\nswitched in\n>>> ', response)

        self._close(conn)

if __name__ == '__main__':
    greentest.main()