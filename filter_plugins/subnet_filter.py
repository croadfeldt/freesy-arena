#!/usr/bin/python
# Custom Ansible Filter to implement the subnet generation logic

from ansible.errors import AnsibleFilterError

def generate_subnet_filter(team_number):
    """
    Generates a subnet string (e.g., '10.12.34.0/24') based on team number rules.
    """
    try:
        team_num_str = str(team_number)
        
        if not 1 <= len(team_num_str) <= 5:
            raise ValueError(f"Team number {team_number} has an invalid length.")

        first_octet = 10
        second_octet = 0
        third_octet = 0
        fourth_octet = 0
        netmask = 24

        if len(team_num_str) <= 3:
            # Team 123 -> 10.0.123.0
            third_octet = int(team_num_str)
        elif len(team_num_str) == 4:
            # Team 1234 -> 10.12.34.0
            second_octet = int(team_num_str[:2])
            third_octet = int(team_num_str[2:])
        elif len(team_num_str) == 5:
            # Team 12345 -> 10.123.45.0
            second_octet = int(team_num_str[:3])
            third_octet = int(team_num_str[3:])

        subnet_cidr = f"{first_octet}.{second_octet}.{third_octet}.{fourth_octet}/{netmask}"
        return subnet_cidr

    except Exception as e:
        raise AnsibleFilterError(f'Subnet filter failed for input {team_number}: {e}')


class FilterModule(object):
    def filters(self):
        return {
            'generate_subnet_filter': generate_subnet_filter
        }
