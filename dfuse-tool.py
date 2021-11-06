#!/usr/bin/env python3
import dfuse
import usb.core
import usb.util
import argparse
import sys

def find_device(args):
    usbdev = usb.core.find(idVendor=args.vid, idProduct=args.pid)

    if usbdev is not None:
        dfu = dfuse.DfuDevice(usbdev)
        for _,alt in dfu.alternates():
            if alt.configuration == args.cfg and alt.bInterfaceNumber == args.intf and alt.bAlternateSetting == args.alt:
                dfu.set_alternate(alt)
                status = dfu.get_status()
                if status[1] == dfuse.DfuState.DFU_ERROR:
                    print("Error cleared: %r" % (status,))
                    dfu.clear_status() # Clear left-over errors
                return dfu

    raise ValueError('No DfuSe compatible device found, check device information options (see --help)')


def list_dfu(args):
    usbdev = usb.core.find(idVendor=args.vid, idProduct=args.pid)

    if usbdev is None:
        raise ValueError('No STM32 DfuSe device found.')

    dfu = find_device(args) #dfuse.DfuDevice(usbdev)
    for name, alt in dfu.alternates():
        print ("Device: [%.4x:%.4x] Cfg: %d Intf: %d Alt: %d '%s'" % ( \
                alt.device.idVendor, \
                alt.device.idProduct, \
                alt.configuration, \
                alt.bInterfaceNumber, \
                alt.bAlternateSetting, \
                name))
        mem = dfu.get_mem_layout()
        print("  memory with %d pages %d bytes, start address %.8x"
            % (mem['pageno'], mem['pagesize'], mem['address']
        ))
        states = ["Readable" if mem['readable'] else "",
                  "Writable" if mem['writable'] else "",
                  "Erasable" if mem['erasable'] else ""]
        print("  device state: %s\n" % ", ".join(states))

def leave_dfu(args):
    dfu = find_device(args)
    dfu.leave()
    status = dfu.get_status()
    if status[0] > 0:
        raise RuntimeError("An error occured. Status: %r %r" %
                             (status[1], dfuse.DfuState.string(status[1])))

def erase(args):
    dfu = find_device(args)
    mem = dfu.get_mem_layout()
    if mem is None:
        end = int(args.erase[1], 0) if len(args.erase) > 1 else 1024
        pagesize = 1024
    elif not mem['erasable']:
        print("Device not erasable, exits now!")
        return
    else:
        end = (int(args.erase[1], 0) if len(args.erase) > 1 else
                    mem['address'] + mem['pagesize'] * mem['pageno'])
        pagesize = mem['pagesize']

    print ("Erasing. Please wait this might be long ...")
    addr = int(args.erase[0], 0) if len(args.erase) else mem['address']
    cnt = 0
    while addr < end:
        dfu.erase(addr)
        dfu.get_status() # must send after erase command page page 16 AN3156
        dfu.wait_while_state(dfuse.DfuState.DFU_DOWNLOAD_BUSY)
        print("Erasing page starting at %.8x" % addr)
        addr += pagesize

    if dfu.get_status()[1] != dfuse.DfuState.DFU_DOWNLOAD_IDLE:
        raise RuntimeError("An error occured. Status: %r %r" %
                             (status[1], dfuse.DfuState.string(status[1])))
    dfu.clear_status()

    print ("Done !")

def flash(args):
    dfufile = args.flash[0]
    dfu = find_device(args)

    mem = dfu.get_mem_layout()
    if mem is not None and not mem['writable']:
        print("Device not writable, exits now!")
        return

    if (dfufile.devInfo['vid'] != dfu.dev.idVendor or dfufile.devInfo['pid'] != dfu.dev.idProduct) and not args.force:
        raise ValueError("Vendor/Product id mismatch: [%.4x:%.4x] (file) [%.4x:%.4x] (device). Trying running with --force" % ( \
                dfufile.devInfo['vid'], \
                dfufile.devInfo['vid'], \
                dfu.dev.idVendor, \
                dfu.dev.idProduct))

    targets = [t for t in dfufile.targets if t['alternate'] == dfu.intf.bAlternateSetting]

    if len(targets) == 0:
        raise ValueError("No file target matches the device. Check the --alt setting")


    print ("Flashing. Please wait this might be long ...")
    for t in targets:
        print ("Found target %r" % t['name'])
        for idx, image in enumerate(t['elements']):
            print("Flashing image %d at 0x%.8X" % (idx, image['address']))

            print("Erasing ...")
            dfu.erase(image['address'])
            status = dfu.wait_while_state(dfuse.DfuState.DFU_DOWNLOAD_BUSY)
            if status[1] != dfuse.DfuState.DFU_DOWNLOAD_IDLE:
                raise RuntimeError("An error occured. Status: %r %r" %
                                     (status[1], dfuse.DfuState.string(status[1])))

            print("Flashing ...")
            transfer_size = mem['pagesize'] if mem else 1024
            _flash(image['address'], transfer_size, image['data'], dfu)

            print("Done")

def flash_bin(args):
    dfu = find_device(args)
    mem = dfu.get_mem_layout()
    if mem is None:
        raise RuntimeError("USB interface description could not be parsed.")
    if not mem['writable']:
        raise RuntimeError("Device not writable.")

    with open(args.flash_bin[0],'rb') as f:
        data = bytearray(f.read())
    if not data:
        raise ValueError("File %r could not be read" % args.flash_bin[0])

    print("Flashing ...")
    transfer_size = mem['pagesize'] if mem else 1024
    _flash(mem['address'], transfer_size, data, dfu)

    print("Done !")

def _flash(address, transfer_size, data, dfu):
    dfu.set_address(address)
    status = dfu.wait_while_state(dfuse.DfuState.DFU_DOWNLOAD_BUSY)
    if status[1] != dfuse.DfuState.DFU_DOWNLOAD_IDLE:
        raise RuntimeError("An error occured. Status: %r %r" %
                            (status[1], dfuse.DfuState.string(status[1])))

    blocks = [data[i:i + transfer_size] for i in range(0, len(data), transfer_size)]
    for blocknum, block in enumerate(blocks):
        print("Flashing block %r %rbytes" % (blocknum, (blocknum + 1) * transfer_size))
        dfu.write(blocknum, block)
        status = dfu.wait_while_state(dfuse.DfuState.DFU_DOWNLOAD_BUSY)
        if status[1] != dfuse.DfuState.DFU_DOWNLOAD_IDLE:
            raise RuntimeError("An error occured. Status: %r %r" %
                                (status[1], dfuse.DfuState.string(status[1])))

    dfu.clear_status()

def read(args):
    dfu = find_device(args)
    mem = dfu.get_mem_layout()
    if mem is not None and not mem['readable']:
        print("Device not readable, exits now!")
        return

    transactions = 0
    maxbytes = mem['pagesize'] * (mem['pageno'] if len(args.read) < 2 else int(args.read[1], 0))
    data = bytearray()
    bytes_read = 0
    bytes_to_read = 0

    print("Copying data from DFU device")

    while bytes_read < maxbytes:
        bytes_to_read = mem['pagesize']
        result = dfu.upload(transactions, bytes_to_read)
        if not result:
            break
        elif transactions == 0:
            transactions += 2
            continue
        elif (len(result) > 0):
            data.extend(result)
            bytes_read += len(result)
        transactions += 1
        print("Read page {0} {1} bytes".format(transactions -3, len(result)))

        if len(result) != bytes_to_read:
            break

    status = dfu.get_status()
    dfu.clear_status()
    if status[1] not in [dfuse.DfuState.DFU_IDLE, dfuse.DfuState.DFU_UPLOAD_IDLE]:
        filename = args.read[0]+'.error'
        with open(filename,'wb') as f:
            f.write(bytearray(data))
        raise RuntimeError("An error occured. Status: %r %r, saved retrieved data to file %r" %
                             (status[1], dfuse.DfuState.string(status[1]), filename))

    print('Done, read {0} bytes'.format(bytes_read))

    with open(args.read[0],'wb') as f:
        f.write(bytearray(data))

parser = argparse.ArgumentParser(description="DfuSe flashing util for STM32")

action = parser.add_mutually_exclusive_group(required = True)
action.add_argument('--list', action='store_true', help='List available DfuSe interfaces')
action.add_argument('--leave', action='store_true', help='Leave DFU mode')
action.add_argument('--flash', nargs=1, action='store', help='Flash a DfuSe file', metavar='FILE', type=dfuse.DfuFile)
action.add_argument('--flash-bin', nargs=1, action='store', help='Flash a ordinary bin file', metavar='FILE', type=str)
action.add_argument('--read', nargs='+', action='store', help='Read device memory', metavar=('SAVEFILE', 'PAGES'), type=str)
action.add_argument('--erase', nargs='*', action='store',
                    help='Erase all or from ADDRESS to page ENDADDR or end of memory (must be page aligned)',
                    metavar=('ADDRESS', 'ENDADDR'))

devinfo = parser.add_argument_group('Device information')
devinfo.add_argument('--vid', action='store', type=int, default=0x0483, help='Device\'s USB vendor id, defaults to 0x0483')
devinfo.add_argument('--pid', action='store', type=int, default=0xdf11, help='Device\'s USB product id, defaults to 0xdf11')
devinfo.add_argument('--cfg', action='store', type=int, default=0, help='Device\'s configuration number, default to 0')
devinfo.add_argument('--intf', action='store', type=int, default=0, help='Device\'s interface number, defaults to 0')
devinfo.add_argument('--alt', action='store', type=int, default=0, help='Device\'s alternate setting number, defaults to 0')

others = parser.add_argument_group('Other Options')
others.add_argument('--force', '-f', action='store_true', help='Bypass sanity checks')

args = parser.parse_args()

try:
#if 1:
    if args.list:
        list_dfu(args)
    elif args.leave:
        leave_dfu(args)
    elif args.erase is not None:
        erase(args)
    elif args.flash is not None:
        flash(args)
    elif args.flash_bin is not None:
        flash_bin(args)
    elif args.read is not None:
        read(args)
except Exception as e:
    print(e, file=sys.stderr)
    sys.exit(-1)
