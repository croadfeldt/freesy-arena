#!/usr/bin/python
# Custom Ansible Filter to implement the subnet generation logic

# Import ipaddress module for robust IP handling in Python
import ipaddress 

def generate_subnet_details_filter(team_number_input):
    """
    Generates a dictionary of subnet details (network, router base, ranges, CIDR) 
    based on team number rules, using robust Python IP libraries.
    Returns None if an error occurs during calculation.
    """
    try:
        team_number = int(team_number_input)
        team_num_str = str(team_number)
        
        if not 1 <= len(team_num_str) <= 5:
            # Returning None instead of raising an AnsibleFilterError
            return None

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
        
        # Calculate broadcast, first assignable, and last assignable IPs
        broadcast_ip = str(network_obj.broadcast_address)
        first_assignable_ip = str(network_obj.network_address + 20) # Start range at .20
        last_assignable_ip = str(network_obj.network_address + 199) # End range at .199

        # Return a dictionary with all required values
        return {
            'network': network_address,
            'subnet_cidr': network_cidr, 
            'base_ip_prefix': f"10.{second_octet}.{third_octet}",
            'cidr_prefix': 24,
            'broadcast_ip': broadcast_ip,
            'first_assignable_ip': first_assignable_ip,
            'last_assignable_ip': last_assignable_ip,
        }

    except (ValueError, TypeError, ipaddress.AddressValueError):
        # Catch any error and return None silently
        return None


class FilterModule(object):
    def filters(self):
        return {
            'generate_subnet_details_filter': generate_subnet_details_filter
        }
