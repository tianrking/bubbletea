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

executable, expectation, output_prefix = sys.argv[1:4]
controlling = len(sys.argv) > 4 and sys.argv[4] == 'controlling'
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 10, 40, 0, 0))
before = termios.tcgetattr(slave)
env = dict(os.environ, TERM='xterm-256color', TERM_PROGRAM='Apple_Terminal')
if expectation == 'baseline-running':
    env['QUIT_LIFECYCLE_SKIP_PRECALL'] = '1'

def acquire_controlling_tty():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)

process = subprocess.Popen([executable], stdin=slave, stdout=slave, stderr=slave,
                           env=env, start_new_session=not controlling,
                           preexec_fn=acquire_controlling_tty if controlling else None)
captured = bytearray()
states = {'initial': before, 'controllingTTY': controlling, 'expectation': expectation}

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
    states['atPrecall'] = termios.tcgetattr(slave)
    if expectation == 'blocked':
        assert not read_until(b'QUIT-LIFECYCLE-RETURNED', 3), 'original Quit unexpectedly returned'
        assert process.poll() is None, 'original process exited unexpectedly'
        assert b'QUIT-LIFECYCLE-READY' not in captured, 'original unexpectedly entered Run'
        states['after'] = termios.tcgetattr(slave)
        assert states['after'] == before, 'blocked original unexpectedly changed terminal state'
        process.kill()
        process.wait(timeout=5)
        result = {'expectation': expectation, 'originalPreRunQuitBlocked': True,
                  'originalNeverEnteredRun': True, 'terminatedOwnedBlockedFixture': True}
    else:
        assert read_until(b'QUIT-LIFECYCLE-READY', 10), 'fixed app did not render its real PTY view'
        assert b'QUIT-LIFECYCLE-RETURNED' in captured, 'Quit did not return before Run'
        active = termios.tcgetattr(slave)
        states['active'] = active
        assert active != before, 'Program never changed real PTY termios to raw input'
        os.write(master, b'q')
        assert read_until(b'QUIT-LIFECYCLE-DONE', 10), 'key q did not terminate Run'
        states['immediateAfterRun'] = termios.tcgetattr(slave)
        os.write(master, b'canonical-after-run')
        assert not read_until(b'QUIT-LIFECYCLE-CANONICAL:', 0.2), 'post-Run input completed before a newline'
        after = termios.tcgetattr(slave)
        states['after'] = after
        assert after == before, 'PTY termios state not preserved/restored'
        os.write(master, b'\n')
        assert read_until(b'QUIT-LIFECYCLE-CANONICAL:canonical-after-run', 5), 'post-Run canonical line was not delivered'
        assert b'canonical-after-run\r\n' in captured, 'post-Run canonical input was not echoed'
        assert process.wait(timeout=5) == 0, 'fixed app returned an error'
        result = {'expectation': expectation, 'preRunQuitReturned': expectation != 'baseline-running',
                  'realPTYViewRendered': True, 'actualRawInputObserved': True,
                  'keyQGracefullyQuit': True, 'nativeExit': 0,
                  'postRunCanonicalLineHeldUntilNewline': True,
                  'postRunCanonicalLineDeliveredAndEchoed': True}
    result.update({'termiosBeforeAfterEqual': True, 'captureBytes': len(captured),
                   'geometry': '40x10', 'platform': sys.platform, 'controllingTTY': controlling})
    Path(output_prefix + '.json').write_text(json.dumps(result, indent=2))
finally:
    Path(output_prefix + '-states.json').write_text(json.dumps(states, indent=2, default=list))
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
    Path(output_prefix + '.bin').write_bytes(captured)
    os.close(master)
    os.close(slave)
