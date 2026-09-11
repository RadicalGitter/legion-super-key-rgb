"""Spectrum 048d:c997 transport; protocol derived from LenovoLegionToolkit.
SPDX-License-Identifier: GPL-3.0-only
"""
import fcntl
import os
from pathlib import Path
import time

SIZE = 960
# LED IDs observed on the tested Legion 7 16IRX9 ISO keyboard.
AVAILABLE_KEYS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 38, 39, 40, 41, 56, 64, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 85, 88, 89, 90, 91, 92, 93, 95, 104, 106, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 121, 123, 124, 127, 128, 130, 131, 135, 136, 141, 142, 144, 146, 150, 151, 152, 154, 155, 156, 157, 159, 161, 163, 165, 167, 168]

class Controller:
    def __init__(self):
        matches = []
        for entry in Path('/sys/class/hidraw').glob('hidraw*'):
            if 'HID_ID=0003:0000048D:0000C997' in (entry / 'device/uevent').read_text():
                matches.append(Path('/dev') / entry.name)
        if len(matches) != 1:
            raise RuntimeError(f'Expected one 048d:c997 controller, found {len(matches)}')
        self.fd = os.open(matches[0], os.O_RDWR | os.O_CLOEXEC)
        try:
            if self.query(0xD1)[4] != 0:
                raise RuntimeError('Controller rejected Spectrum compatibility query')
        except BaseException:
            os.close(self.fd)
            raise

    def send(self, data):
        if len(data) != SIZE or data[0] != 7:
            raise ValueError('Invalid Spectrum report')
        fcntl.ioctl(self.fd, (3 << 30) | (SIZE << 16) | (ord('H') << 8) | 6, bytearray(data))

    def command(self, operation, *parameters):
        self.send(bytes([7, operation, 0xC0, 3, *parameters]).ljust(SIZE, b'\0'))

    def query(self, operation, *parameters):
        self.command(operation, *parameters)
        # This firmware can return the previous response if polled immediately.
        time.sleep(0.05)
        data = bytearray(SIZE)
        data[0] = 7
        fcntl.ioctl(self.fd, (3 << 30) | (SIZE << 16) | (ord('H') << 8) | 7, data, True)
        if data[0] != 7 or data[1] != operation:
            raise RuntimeError(f'Unexpected reply to {operation:02x}: {data[:8].hex()}')
        if operation == 0xCC and data[4] != parameters[0]:
            raise RuntimeError('Controller returned a different profile; refusing to use it')
        return bytes(data)
