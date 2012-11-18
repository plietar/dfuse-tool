import usb.util
import time

DFU_REQUEST_SEND = 0x21
DFU_REQUEST_RECEIVE = 0xa1

DFU_DETACH    = 0x00
DFU_DNLOAD    = 0x01
DFU_UPLOAD    = 0x02
DFU_GETSTATUS = 0x03
DFU_CLRSTATUS = 0x04
DFU_GETSTATE  = 0x05
DFU_ABORT     = 0x06

# Order is LSB first
def address_to_4bytes(a):
    return [ a % 256, (a >> 8)%256, (a >> 16)%256, (a >> 24)%256 ]

class DfuDevice:
    def __init__(self, device):
        self.dev = device
        self.cfg = self.dev[0]
        self.intf = None
        #self.dev.reset()
        self.cfg.set()

    def alternates(self):
        return [(self.get_string(intf.iInterface), intf) for intf in self.cfg]

    def set_alternate(self, intf):
        if isinstance(intf, tuple):
            self.intf = intf[1]
        else:
            self.intf = intf
        
        self.intf.set_altsetting()

    def control_msg(self, requestType, request, value, buffer):
        return self.dev.ctrl_transfer(requestType, request, value, self.intf.bInterfaceNumber, buffer)

    def detach(self, timeout):
        return self.control_msg(DFU_REQUEST_SEND, DFU_DETACH, timeout, None)
    
    def dnload(self, blockNum, data):
        return self.control_msg(DFU_REQUEST_SEND, DFU_DNLOAD, blockNum, data)
    
    def upload(self, blockNum, size):
        return self.control_msg(DFU_REQUEST_RECEIVE, DFU_UPLOAD, blockNum, size)

    def get_status(self):
        status = self.control_msg(DFU_REQUEST_RECEIVE, DFU_GETSTATUS, 0, 6)
        return (status[0], status[4], status[1] + (status[2] << 8) + (status[3] << 16), status[5])
    
    def clear_status(self):
        self.control_msg(DFU_REQUEST_SEND, DFU_CLRSTATUS, 0, None)

    def get_state(self):
        return self.control_msg(DFU_REQUEST_RECEIVE, DFU_GETSTATE, 0, 1)[0]

    def set_address(self, ap):
        return self.dnload(0x0, [0x21] + address_to_4bytes(ap))

    def write(self, block, data):
        return self.dnload(block + 2, data)
    
    def erase(self, pa):
        return self.dnload(0x0, [0x41] + address_to_4bytes(pa))

    def leave(self):
        return self.dnload(0x0, []) # Just send an empty data.

    def get_string(self, index):
        return usb.util.get_string(self.dev, 256, index)

    def wait_while_state(self, state):
        if not isinstance(state, (list, tuple)):
            states = (state,)
        else:
            states = state

        status = self.get_status()
        
        while (status[1] in states):
            status = self.get_status()
            time.sleep(status[2] / 1000)
        
        return status

