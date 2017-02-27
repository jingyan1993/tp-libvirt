import os
import copy
import ast
import logging

from avocado.utils import process
from avocado.core import exceptions

from virttest import virsh
from virttest import utils_config, utils_libvirtd
from virttest import data_dir
from virttest.libvirt_xml import vm_xml
from virttest.utils_test import libvirt


def run(test, params, env):
    """
    Test vcpu hotpluggable item in xml

    1. Set the libvirtd log filter/level/file
    2. Restart libvirtd
    3. Start vm by xml with vcpu hotpluggable
    4. Check the qemu command line
    5. Check the libvirtd log
    6. Restart libvrtd
    7. Check the vm xml
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vcpus_placement = params.get("vcpus_placement", "static")
    vcpus_current = int(params.get("vcpus_current", "3"))
    vcpus_max = int(params.get("vcpus_max", "6"))
    vcpus_enabled = params.get("vcpus_enabled", "")
    vcpus_hotplug = params.get("vcpus_hotpluggable", "")
    vcpus_order = params.get("vcpus_order")
    err_msg = params.get("err_msg", "")
    config_libvirtd = params.get("config_libvirtd", "yes")
    log_file = params.get("log_file", "libvirtd.log")
    log_path = os.path.join(data_dir.get_tmp_dir(), log_file)
    log_outputs = "1:file:%s" % log_path
    log_level = 1
    log_filters = "1:json 1:libvirt 1:qemu 1:monitor 3:remote 4:event"

    # Back up domain XML
    vmxml_bak = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    libvirtd = utils_libvirtd.Libvirtd()

    try:
        # Update libvirtd log file/level/filter
        config = utils_config.LibvirtdConfig()
        config.log_outputs = log_outputs
        config.log_level = log_level
        config.log_filters = log_filters

        # Restart libvirtd to make the changes take effect in libvirt
        libvirtd.restart()

        # Define vm with vcpu hotpluggable
        vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)

        # Set vcpu: placement,current,max vcpu
        vmxml.placement = vcpus_placement
        vmxml.vcpu = vcpus_max
        vmxml.current_vcpu = vcpus_current
        del vmxml.cpuset

        # create vcpu xml
        vcpu_list = []
        vcpu = {}
        en_list = vcpus_enabled.split(",")
        hotplug_list = vcpus_hotplug.split(",")
        order_dict = ast.literal_eval(vcpus_order)

        for i in range(vcpus_max):
            vcpu['id'] = str(i)
            if str(i) in en_list:
                vcpu['enabled'] = 'yes'
                if order_dict.has_key(str(i)):
                    vcpu['order'] = order_dict[str(i)]
            else:
                vcpu['enabled'] = 'no'
            if str(i) in hotplug_list:
                vcpu['hotpluggable'] = 'yes'
            else:
                vcpu['hotpluggable'] = 'no'
            vcpu_list.append(copy.copy(vcpu))
            vcpu = {}

        vcpus_xml = vm_xml.VMVCPUSXML()
        vcpus_xml.vcpu = vcpu_list

        vmxml.vcpus = vcpus_xml
        vmxml.sync()

        # Start VM
        logging.info("Start VM with vcpu hotpluggable and order...")
        ret = virsh.start(vm_name, ignore_status=True)
        if err_msg:
            libvirt.check_result(ret, err_msg)
        else:
            # Check QEMU command line
            cmd = ("ps -ef| grep %s| grep 'maxcpus=%s'" % (vm_name, vcpus_max))
            process.run(cmd, ignore_status=False, shell=True)

            # Dumpxml
            dump_xml = virsh.dumpxml(vm_name).stdout.strip()

            # Check libvirtd log
            for vcpu in vcpu_list:
                if vcpu['enabled'] == 'yes' and vcpu['hotpluggable'] == 'yes':
                    cmd = ("cat %s| grep device_add| grep qemuMonitorIOWrite"
                           "| grep 'vcpu%s'" % (log_path, vcpu['id']))
                    logging.info("cmd:\n %s" % cmd)
                    process.run(cmd, ignore_status=False, shell=True)

            # Restart libvirtd
            libvirtd.restart()

            # Recheck VM xml
            re_dump_xml = virsh.dumpxml(vm_name).stdout.strip()
            if cmp(dump_xml, re_dump_xml) != 0:
                raise exceptions.TestFail("The VM xml changed after restarting libvirtd.")

    finally:
        # Recover libvirtd configration
        config.restore()

        # Recover VM
        if vm.is_alive():
            vm.destroy(gracefully=False)
        vmxml_bak.sync()
