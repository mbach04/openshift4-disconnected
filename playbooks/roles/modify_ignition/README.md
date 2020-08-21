# Ansible role 'modify_ignition'

Ansible role for modifying ignition configs generated by the openshift install client.
Modifying the ignition configs is necessary in static IP environments so the ignition config for each
host is unique and contains unique information for each host like IP address information

## Requirements

- No Requirements

## Dependencies

- No Dependencies

## Role Variables

| Variable             | Default                       | Comments                                                                                |
| :---                 | :---                          | :---                                                                                    |
| filetranspiler       |
| fake_root_base       |

Example Playbook
----------------

Including an example of how to use your role (for instance, with variables passed in as parameters) is always nice for users too:

    - hosts: servers
      roles:
         - { role: username.rolename, x: 42 }

## License

2-clause BSD license, see [LICENSE.md](LICENSE.md)

## Contributors

- [Dan Clark](https://github.com/dmc5179/) (maintainer)