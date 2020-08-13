#
# Author: Bo Maryniuk <bo@suse.de>
#
# Copyright 2017 SUSE LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import salt.modules.ansiblegate as ansible
import salt.utils.platform
from salt.exceptions import LoaderError
from salt.ext import six
from tests.support.mixins import LoaderModuleMockMixin
from tests.support.mock import MagicMock, MockTimedProc, patch
from tests.support.unit import TestCase, skipIf

try:
    import pytest
except ImportError as import_error:
    pytest = None
NO_PYTEST = not bool(pytest)


@skipIf(NO_PYTEST, False)
@skipIf(salt.utils.platform.is_windows(), "Not supported on Windows")
class AnsiblegateTestCase(TestCase, LoaderModuleMockMixin):
    def setUp(self):
        self.resolver = ansible.AnsibleModuleResolver({})
        self.resolver._modules_map = {
            "one.two.three": os.sep + os.path.join("one", "two", "three.py"),
            "four.five.six": os.sep + os.path.join("four", "five", "six.py"),
            "three.six.one": os.sep + os.path.join("three", "six", "one.py"),
        }

    def tearDown(self):
        self.resolver = None

    def setup_loader_modules(self):
        return {ansible: {}}

    def test_ansible_module_help(self):
        """
        Test help extraction from the module
        :return:
        """

        class Module:
            """
            An ansible module mock.
            """

            __name__ = "foo"
            DOCUMENTATION = """
---
one:
   text here
---
two:
   text here
description:
   describe the second part
        """

        with patch.object(ansible, "_resolver", self.resolver), patch.object(
            ansible._resolver, "load_module", MagicMock(return_value=Module())
        ):
            ret = ansible.help("dummy")
            assert sorted(
                ret.get('Available sections on module "{}"'.format(Module().__name__))
            ) == ["one", "two"]
            assert ret.get("Description") == "describe the second part"

    def test_module_resolver_modlist(self):
        """
        Test Ansible resolver modules list.
        :return:
        """
        assert self.resolver.get_modules_list() == [
            "four.five.six",
            "one.two.three",
            "three.six.one",
        ]
        for ptr in ["five", "fi", "ve"]:
            assert self.resolver.get_modules_list(ptr) == ["four.five.six"]
        for ptr in ["si", "ix", "six"]:
            assert self.resolver.get_modules_list(ptr) == [
                "four.five.six",
                "three.six.one",
            ]
        assert self.resolver.get_modules_list("one") == [
            "one.two.three",
            "three.six.one",
        ]
        assert self.resolver.get_modules_list("one.two") == ["one.two.three"]
        assert self.resolver.get_modules_list("four") == ["four.five.six"]

    def test_resolver_module_loader_failure(self):
        """
        Test Ansible module loader.
        :return:
        """
        mod = "four.five.six"
        with pytest.raises(ImportError) as import_error:
            self.resolver.load_module(mod)

        mod = "i.even.do.not.exist.at.all"
        with pytest.raises(LoaderError) as loader_error:
            self.resolver.load_module(mod)

    def test_resolver_module_loader(self):
        """
        Test Ansible module loader.
        :return:
        """
        with patch("salt.modules.ansiblegate.importlib", MagicMock()), patch(
            "salt.modules.ansiblegate.importlib.import_module", lambda x: x
        ):
            assert (
                self.resolver.load_module("four.five.six")
                == "ansible.modules.four.five.six"
            )

    def test_resolver_module_loader_import_failure(self):
        """
        Test Ansible module loader failure.
        :return:
        """
        with patch("salt.modules.ansiblegate.importlib", MagicMock()), patch(
            "salt.modules.ansiblegate.importlib.import_module", lambda x: x
        ):
            with pytest.raises(LoaderError) as loader_error:
                self.resolver.load_module("something.strange")

    def test_virtual_function(self):
        """
        Test Ansible module __virtual__ when ansible is not installed on the minion.
        :return:
        """
        with patch("salt.modules.ansiblegate.ansible", None):
            assert ansible.__virtual__() == "ansible"

    def test_ansible_module_call(self):
        """
        Test Ansible module call from ansible gate module

        :return:
        """

        class Module:
            """
            An ansible module mock.
            """

            __name__ = "one.two.three"
            __file__ = "foofile"

            def main():
                pass

        ANSIBLE_MODULE_ARGS = '{"ANSIBLE_MODULE_ARGS": ["arg_1", {"kwarg1": "foobar"}]}'

        proc = MagicMock(
            side_effect=[
                MockTimedProc(stdout=ANSIBLE_MODULE_ARGS.encode(), stderr=None),
                MockTimedProc(stdout=b'{"completed": true}', stderr=None),
            ]
        )

        with patch.object(ansible, "_resolver", self.resolver), patch.object(
            ansible._resolver, "load_module", MagicMock(return_value=Module())
        ):
            _ansible_module_caller = ansible.AnsibleModuleCaller(ansible._resolver)
            with patch("salt.utils.timed_subprocess.TimedProc", proc):
                ret = _ansible_module_caller.call(
                    "one.two.three", "arg_1", kwarg1="foobar"
                )
                proc.assert_any_call(
                    ["python3", "foofile"],
                    stdin=ANSIBLE_MODULE_ARGS,
                    stdout=-1,
                    timeout=1200,
                )
                try:
                    proc.assert_any_call(
                        [
                            "echo",
                            '{"ANSIBLE_MODULE_ARGS": {"kwarg1": "foobar", "_raw_params": "arg_1"}}',
                        ],
                        stdout=-1,
                        timeout=1200,
                    )
                except AssertionError:
                    proc.assert_any_call(
                        [
                            "echo",
                            '{"ANSIBLE_MODULE_ARGS": {"_raw_params": "arg_1", "kwarg1": "foobar"}}',
                        ],
                        stdout=-1,
                        timeout=1200,
                    )
                assert ret == {"completed": True, "timeout": 1200}

    @patch("salt.utils.path.which", MagicMock(return_value=True))
    def test_ansible_playbooks_return_retcode(self):
        """
        Test ansible.playbooks execution module function include retcode in the return.
        :return:
        """
        ref_out = {"retcode": 0, "stdout": '{"foo": "bar"}'}
        cmd_run_all = MagicMock(return_value=ref_out)
        with patch.dict(ansible.__salt__, {"cmd.run_all": cmd_run_all}):
            ret = ansible.playbooks("fake-playbook.yml")
            assert "retcode" in ret
