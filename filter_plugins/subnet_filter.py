#!/usr/bin/python
# Custom Ansible Filter to implement the subnet generation logic

from ansible.errors import AnsibleFilterError
# Import ipaddress module for robust IP handling in Python
import ipaddress 

def generate_subnet_details_filter(team_number_input):
    """
    Generates a dictionary of subnet details (network, router base, ranges) 
    based on team number rules, using robust Python IP libraries.
    """
    try:
        team_number = int(team_number_input)
        team_num_str = str(team_number)
        
        if not 1 <= len(team_num_str) <= 5:
            raise ValueError(f"Team number {team_number} has an invalid length.")

        second_octet = 0
        third_octet = 0

        if len(team_num_str) <= 3:
            third_octet = team_number
        elif len(team_num_str) == 4:
            second_octet = int(team_num_str[:2])
            third_octet = int(team_num_str[2:])
        elif len(team_num_str) == 5:
            second_octet = int(team_num_str[:3])
            third_octet = int(team_num_str[3:])

        # Use Python's ipaddress module to calculate network details reliably
        network_cidr = f"10.{second_octet}.{third_octet}.0/24"
        network_obj = ipaddress.IPv4Network(network_cidr)
        network_address = str(network_obj.network_address)
        
        # Return a dictionary with all required values
        return {
            'network': network_address,
            # Placeholder for last octet in router IP, we add it in the playbook
            'base_ip_prefix': f"10.{second_octet}.{third_octet}",
            'range_start': f"10.{second_octet}.{third_octet}.20",
            'range_end': f"10.{second_octet}.{third_octet}.199"
        }

    except (ValueError, TypeError, ipaddress.AddressValueError) as e:
        raise AnsibleFilterError(f'Subnet filter failed for input "{team_number_input}": {e}')


class FilterModule(object):
    def filters(self):
        return {
            # Rename the filter to reflect its new functionality
            'generate_subnet_details_filter': generate_subnet_details_filter
        }
