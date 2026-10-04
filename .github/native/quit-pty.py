import errno
import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

executable, expectation, output_prefix = sys.argv[1:]
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 10, 40, 0, 0))
before = termios.tcgetattr(slave)
env = dict(os.environ, TERM='xterm-256color', TERM_PROGRAM='Apple_Terminal')
process = subprocess.Popen([executable], stdin=slave, stdout=slave, stderr=slave,
                           env=env, start_new_session=True)
captured = bytearray()

def read_until(marker, seconds):
    deadline = time.monotonic() + seconds
    while marker not in captured and time.monotonic() < deadline:
        ready, _, _ = select.select([master], [], [], min(0.1, deadline - time.monotonic()))
        if ready:
            try:
                data = os.read(master, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not data:
                break
            captured.extend(data)
    return marker in captured

try:
    assert read_until(b'QUIT-LIFECYCLE-PRECALL', 10), 'probe did not enter Quit'
    if expectation == 'blocked':
        assert not read_until(b'QUIT-LIFECYCLE-RETURNED', 3), 'original Quit unexpectedly returned'
        assert process.poll() is None, 'original process exited unexpectedly'
        assert b'QUIT-LIFECYCLE-READY' not in captured, 'original unexpectedly entered Run'
        process.kill()
        process.wait(timeout=5)
        result = {'expectation': expectation, 'originalPreRunQuitBlocked': True,
                  'originalNeverEnteredRun': True, 'terminatedOwnedBlockedFixture': True}
    else:
        assert read_until(b'QUIT-LIFECYCLE-READY', 10), 'fixed app did not render its real PTY view'
        assert b'QUIT-LIFECYCLE-RETURNED' in captured, 'Quit did not return before Run'
        active = termios.tcgetattr(slave)
        assert active != before, 'Program never changed real PTY termios to raw input'
        os.write(master, b'q')
        assert read_until(b'QUIT-LIFECYCLE-DONE', 10), 'key q did not terminate Run'
        assert process.wait(timeout=5) == 0, 'fixed app returned an error'
        result = {'expectation': expectation, 'preRunQuitReturned': True,
                  'realPTYViewRendered': True, 'actualRawInputObserved': True,
                  'keyQGracefullyQuit': True, 'nativeExit': 0}
    after = termios.tcgetattr(slave)
    assert after == before, 'PTY termios state not preserved/restored'
    result.update({'termiosBeforeAfterEqual': True, 'captureBytes': len(captured),
                   'geometry': '40x10', 'platform': sys.platform})
    Path(output_prefix + '.json').write_text(json.dumps(result, indent=2))
finally:
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
    Path(output_prefix + '.bin').write_bytes(captured)
    os.close(master)
    os.close(slave)
