#!/usr/bin/python
# Custom Ansible Filter to implement the subnet generation logic

from ansible.errors import AnsibleFilterError

def generate_subnet_filter(team_number_input):
    """
    Generates a subnet string (e.g., '10.12.34.0/24') based on team number rules.
    Expects an integer or a string that can be cast to an integer.
    """
    try:
        # Explicitly cast the input to an integer immediately
        team_number = int(team_number_input)
        
        # Now use the integer 'team_number' for all subsequent logic
        team_num_str = str(team_number)
        
        if not 1 <= len(team_num_str) <= 5:
            # Raise an error if the number itself is out of expected range
            raise ValueError(f"Team number {team_number} has an invalid length.")

        first_octet = 10
        second_octet = 0
        third_octet = 0
        fourth_octet = 0
        netmask = 24

        if len(team_num_str) <= 3:
            # Team 123 -> 10.0.123.0
            third_octet = team_number
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

    except (ValueError, TypeError) as e:
        # Catch specific casting errors and provide a clear Ansible error
        raise AnsibleFilterError(f'Subnet filter failed: Input "{team_number_input}" could not be converted to a valid integer: {e}')
    except Exception as e:
        # Catch any other unexpected errors
        raise AnsibleFilterError(f'Subnet filter failed for input {team_number_input}: {e}')


class FilterModule(object):
    def filters(self):
        return {
            'generate_subnet_filter': generate_subnet_filter
        }
