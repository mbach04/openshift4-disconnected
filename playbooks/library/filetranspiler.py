#!/usr/bin/python

# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import abc 
import argparse
import base64
import json
import magic
import os
import pathlib
import stat
import yaml

from ansible.module_utils.basic import AnsibleModule

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: filetranspiler

short_description: Creates an Ignition JSON file from a fake root.

version_added: "2.4"

description:
    - "This is my longer description explaining my test module"

options:
    name:
        description:
            - This is the message to send to the test module
        required: true
    new:
        description:
            - Control to demo if the result of this module is changed or not
        required: false

author:
    - Dan Clark (@dmc5179)
'''

EXAMPLES = '''
# Pass in a message
- name: Test with a message
  my_test:
    name: hello world

# pass in a message and have changed true
- name: Test with a message and changed output
  my_test:
    name: hello world
    new: true

# fail the module
- name: Test failure of the module
  my_test:
    name: fail me
'''

RETURN = '''
original_message:
    description: The original name param that was passed in
    type: str
    returned: always
message:
    description: The output message that the test module generates
    type: str
    returned: always
'''

__version__ = '1.1.2'


class FileTranspilerError(Exception):
    """
    Base exception for FileTranspiler errors.
    """
    pass


class IgnitionSpec(abc.ABC):
    """
    Base class for IgnitionSpec classes.
    """

    def __init__(self, ignition_cfg, cli_args):
        """
        Initialize a spec merger.

        :param ignition_cfg: loaded ignition config json
        :type ignition_cfg: dict
        :param cli_args: Command line arguments
        :type cli_args: argparse.Namespace
        """
        self.ignition_cfg = ignition_cfg
        self.fake_root = cli_args['fake_root']
        self.dereference_symlinks = cli_args['dereference_symlinks']
        self.mimetype = magic.open(magic.MAGIC_MIME)
        self.mimetype.load()

    def __del__(self):
        self.mimetype.close()

    @abc.abstractmethod
    def file_to_ignition(self, file_path, file_contents, mode):
        """
        Turns a file into an ignition snippet.

        :param file_path: Path to where the file should be placed.
        :type file_path: str
        :param file_contents: The header and transformed contents of the file
        :type file_contents: str
        :param mode: Octal mode to use (will translate to decimal)
        :type mode: int
        :returns: Ignition config snippet
        :rtype: dict
        """
        raise NotImplementedError('Must be implemented in a subclass')

    def _encode_contents(self, file_path):
        """
        Internal encoding of contents.

        :param file_path: Path to where the file is located.
        :type file_path: str
        :returns: Encoded file_contents
        :rtype: str
        """
        header = ''.join(self.mimetype.file(file_path).split(' '))
        with open(file_path, 'rb') as file_obj:
            contents_base64 = base64.b64encode(
                file_obj.read())
            file_contents = 'data:{};base64,{}'.format(
                header, contents_base64.decode('utf8'))
            return file_contents

    @abc.abstractmethod
    def link_to_ignition(self, file_path, target_path):
        """
        Turns a symbolic link into an ignition snippet.

        :param file_path: Path to where the file should be placed.
        :type file_path: str
        :param target_path: The target path of the symbolic link
        :type target_path: str
        :returns: Ignition config snippet
        :rtype: dict
        """
        raise NotImplementedError('Must be implemented in a subclass')

    def merge_with_ignition(self, ignition_cfg, files, links):
        """
        Merge file snippets into the ignition config.

        :param ignition_cfg: Ignition structure to append to
        :type ignition_cfg: dict
        :param files: List of Ignition file snippets
        :type files: list
        :returns: Merged ignition dict
        :rtype: dict
        """
        # Check that the storage exists
        storage_check = ignition_cfg.get('storage')
        if storage_check is None:
            ignition_cfg['storage'] = {}

        if files:
            # Check that files entry exists
            files_check = ignition_cfg['storage'].get('files')
            if files_check is None:
                ignition_cfg['storage']['files'] = []

            for a_file in files:
                ignition_cfg['storage']['files'].append(a_file)

        if links:
            # Check that links entry exists
            links_check = ignition_cfg['storage'].get('links')
            if links_check is None:
                ignition_cfg['storage']['links'] = []

            for a_link in links:
                ignition_cfg['storage']['links'].append(a_link)

        return ignition_cfg

    def merge(self):
        """
        Merges the fakeroot into the ignition config.

        :returns: The merged ignition config
        :rtype: dict
        """
        # Walk through the files and append them for merging
        all_files = []
        all_links = []
        for root, _, files in os.walk(self.fake_root):
            for file in files:
                path = os.path.sep.join([root, file])
                host_path = path.replace(self.fake_root, '')
                if not host_path.startswith(os.path.sep):
                    host_path = os.path.sep + host_path
                if os.path.islink(path):
                    # If we are dereferencing symlinks then treat it as
                    # a file
                    if self.dereference_symlinks:
                        source_path = str(pathlib.Path(path).resolve())
                        # Ensure the path is within the fakeroot
                        if not source_path.startswith(
                                os.path.realpath(self.fake_root)):
                            raise FileTranspilerError(
                                'link: {} is not in the fake root: {}'.format(
                                    source_path, self.fake_root))
                        mode = oct(stat.S_IMODE(os.stat(source_path).st_mode))
                        snippet = self.file_to_ignition(
                            host_path,
                            self._encode_contents(source_path),
                            mode)
                        all_files.append(snippet)
                    else:
                        target_path = os.readlink(path)
                        snippet = self.link_to_ignition(
                            host_path, target_path)
                        all_links.append(snippet)
                else:
                    mode = oct(stat.S_IMODE(os.stat(path).st_mode))
                    snippet = self.file_to_ignition(
                        host_path, self._encode_contents(path), mode)
                    all_files.append(snippet)

        # Merge the and output the results
        merged_ignition = self.merge_with_ignition(
            self.ignition_cfg, all_files, all_links)
        return merged_ignition


class SpecV2(IgnitionSpec):
    """
    Spec v2 implementation for merging files.
    """

    def file_to_ignition(self, file_path, file_contents, mode):
        """
        Turns a file into an ignition snippet.

        :param file_path: Path to where the file should be placed.
        :type file_path: str
        :param file_contents: The header and transformed contents of the file
        :type file_contents: str
        :param mode: Octal mode to use (will translate to decimal)
        :type mode: int
        :returns: Ignition config snippet
        :rtype: dict
        """
        return {
            'path': file_path,
            "filesystem": 'root',
            'mode': int(mode, 8),
            'contents': {
                'source': file_contents,
            }
        }

    def link_to_ignition(self, file_path, target_path):
        """
        Turns a symbolic link into an ignition snippet.

        :param file_path: Path to where the file should be placed.
        :type file_path: str
        :param target_path: The target path of the symbolic link
        :type target_path: str
        :returns: Ignition config snippet
        :rtype: dict
        """
        return {
            'path': file_path,
            "filesystem": 'root',
            'target' : target_path,
            'hard': False
        }


class SpecV3(IgnitionSpec):
    """
    Spec v3 implementation for merging files.
    """

    def file_to_ignition(self, file_path, file_contents, mode):
        """
        Turns a file into an ignition snippet.

        :param file_path: Path to where the file should be placed.
        :type file_path: str
        :param file_contents: The header and transformed contents of the file
        :type file_contents: str
        :param mode: Octal mode to use (will translate to decimal)
        :type mode: int
        :returns: Ignition config snippet
        :rtype: dict
        """
        return {
            'path': file_path,
            'mode': int(mode, 8),
            'overwrite': True,
            'contents': {
                'source': file_contents,
            }
        }

    def link_to_ignition(self, file_path, target_path):
        """
        Turns a symbolic link into an ignition snippet.

        :param file_path: Path to where the file should be placed.
        :type file_path: str
        :param target_path: The target path of the symbolic link
        :type target_path: str
        :returns: Ignition config snippet
        :rtype: dict
        """
        return {
            'path': file_path,
            'overwrite': True,
            'target' : target_path,
            'hard': False
        }


def loader(ignition_file):
    """
    Loads the ignition json into a structure, senses the ignition
    spec version, and returns the structure and it's spec class.

    :param ignition_file: Path to the ignition file to parse
    :type ignition_file: str
    :returns: The ignition structure and spec class
    :rtype: tuple
    :raises: FileTranspilerError
    """
    try:
        with open(ignition_file, 'r') as f:
            ignition_cfg = json.load(f)
        ignition_version = ignition_cfg['ignition']['version']
        version_tpl = ignition_version.split('.')

        if version_tpl[0] == '2':
            return ignition_cfg, SpecV2
        elif version_tpl[0] == '3':
            return ignition_cfg, SpecV3
        raise FileTranspilerError(
            'Unkown ignition spec: {}'.format(ignition_version))
    except (KeyError, IndexError) as err:
        raise FileTranspilerError(
            'Unable to find version in spec: {}'.format(err))
    except json.JSONDecodeError as err:
        raise FileTranspilerError(
            'Unable to read JSON: {}'.format(err))

def main():

    global module

    module = AnsibleModule(
        argument_spec=dict(
            ignition=dict(type='path', required=True),
            fake_root=dict(type='path', required=True),
            output=dict(type='path', required=True),
            pretty=dict(type='bool', default=False),
            dereference_symlinks=dict(type='bool', default=False),
            output_format=dict(type='str', choices=['json', 'yaml'])
        ),
        supports_check_mode=False,
    )

    # Open the base ignition file and load it
    # Get the ignition config
    try:
        ignition_cfg, spec_cls = loader(module.params['ignition'])
        ignition_spec = spec_cls(ignition_cfg, module.params)
    except FileTranspilerError as err:
        parser.error(err)

    # Merge the and output the results
    merged_ignition = ignition_spec.merge()

    if module.params['output_format'] == 'json':
        if module.params['pretty']:
            ignition_out = json.dumps(
                merged_ignition, sort_keys=True,
                indent=4, separators=(',', ': '))
        else:
            ignition_out = json.dumps(merged_ignition)
    else:
        ignition_out = yaml.safe_dump(merged_ignition)

    with open(module.params['output'], 'w') as out_f:
        out = out_f.write(ignition_out)

    result = {'dest': module.params['output']}
    result['path'] = module.params['output']
    result['changed'] = out

    module.exit_json(**result)


if __name__ == '__main__':
    main()
