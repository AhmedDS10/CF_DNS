#!/usr/bin/env python3
"""
Cloudflare Dynamic DNS Updater
Monitors your public IP address and updates Cloudflare DNS records when it changes.
"""

import requests
import time
import json
import sys
from pathlib import Path

# Configuration
CONFIG = {
    'CF_API_TOKEN': 'your_cloudflare_api_token_here',
    'CF_ZONE_ID': 'your_zone_id_here',
    'CF_RECORD_NAME': 'subdomain.example.com',  # The DNS record to update
    'CHECK_INTERVAL': 300,  # Check every 5 minutes (in seconds)
    'IP_CHECK_SERVICES': [
        'https://api.ipify.org',
        'https://ifconfig.me/ip',
        'https://icanhazip.com'
    ]
}

# File to store last known IP
IP_CACHE_FILE = Path.home() / '.cloudflare_ddns_ip.txt'

class CloudflareDDNS:
    def __init__(self, api_token, zone_id, record_name):
        self.api_token = api_token
        self.zone_id = zone_id
        self.record_name = record_name
        self.base_url = 'https://api.cloudflare.com/client/v4'
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
    
    def get_public_ip(self):
        """Get current public IP address from multiple services."""
        for service in CONFIG['IP_CHECK_SERVICES']:
            try:
                response = requests.get(service, timeout=5)
                if response.status_code == 200:
                    ip = response.text.strip()
                    print(f"✓ Current IP: {ip}")
                    return ip
            except Exception as e:
                print(f"✗ Failed to get IP from {service}: {e}")
                continue
        
        print("✗ ERROR: Could not determine public IP from any service")
        return None
    
    def get_cached_ip(self):
        """Read last known IP from cache file."""
        try:
            if IP_CACHE_FILE.exists():
                return IP_CACHE_FILE.read_text().strip()
        except Exception as e:
            print(f"Warning: Could not read cached IP: {e}")
        return None
    
    def save_cached_ip(self, ip):
        """Save current IP to cache file."""
        try:
            IP_CACHE_FILE.write_text(ip)
        except Exception as e:
            print(f"Warning: Could not save cached IP: {e}")
    
    def get_dns_record(self):
        """Get the DNS record details from Cloudflare."""
        url = f'{self.base_url}/zones/{self.zone_id}/dns_records'
        params = {'name': self.record_name}
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data['success'] and data['result']:
                return data['result'][0]
            else:
                print(f"✗ DNS record not found: {self.record_name}")
                return None
        except Exception as e:
            print(f"✗ Error fetching DNS record: {e}")
            return None
    
    def update_dns_record(self, record_id, new_ip):
        """Update the DNS record with new IP address."""
        url = f'{self.base_url}/zones/{self.zone_id}/dns_records/{record_id}'
        
        record = self.get_dns_record()
        if not record:
            return False
        
        data = {
            'type': record['type'],
            'name': record['name'],
            'content': new_ip,
            'ttl': record.get('ttl', 1),
            'proxied': record.get('proxied', False)
        }
        
        try:
            response = requests.put(url, headers=self.headers, json=data)
            response.raise_for_status()
            result = response.json()
            
            if result['success']:
                print(f"✓ DNS record updated successfully!")
                print(f"  {self.record_name} → {new_ip}")
                return True
            else:
                print(f"✗ Failed to update DNS record: {result.get('errors', [])}")
                return False
        except Exception as e:
            print(f"✗ Error updating DNS record: {e}")
            return False
    
    def check_and_update(self):
        """Main function to check IP and update if changed."""
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Checking IP address...")
        
        # Get current public IP
        current_ip = self.get_public_ip()
        if not current_ip:
            return False
        
        # Get cached IP
        cached_ip = self.get_cached_ip()
        
        # Check if IP has changed
        if current_ip == cached_ip:
            print("✓ IP address unchanged, no update needed")
            return True
        
        print(f"! IP address changed: {cached_ip} → {current_ip}")
        
        # Get DNS record
        record = self.get_dns_record()
        if not record:
            return False
        
        # Update DNS record
        if self.update_dns_record(record['id'], current_ip):
            self.save_cached_ip(current_ip)
            return True
        
        return False
    
    def run_monitor(self):
        """Continuously monitor and update IP address."""
        print("=" * 60)
        print("Cloudflare Dynamic DNS Updater")
        print("=" * 60)
        print(f"Monitoring: {self.record_name}")
        print(f"Check interval: {CONFIG['CHECK_INTERVAL']} seconds")
        print(f"Press Ctrl+C to stop")
        print("=" * 60)
        
        try:
            while True:
                self.check_and_update()
                time.sleep(CONFIG['CHECK_INTERVAL'])
        except KeyboardInterrupt:
            print("\n\n✓ Monitoring stopped by user")
            sys.exit(0)


def main():
    # Validate configuration
    if CONFIG['CF_API_TOKEN'] == 'your_cloudflare_api_token_here':
        print("ERROR: Please configure your Cloudflare API token in the script")
        print("\nTo get your API token:")
        print("1. Go to https://dash.cloudflare.com/profile/api-tokens")
        print("2. Create a token with 'Edit DNS' permissions")
        sys.exit(1)
    
    if CONFIG['CF_ZONE_ID'] == 'your_zone_id_here':
        print("ERROR: Please configure your Cloudflare Zone ID")
        print("\nTo find your Zone ID:")
        print("1. Go to your Cloudflare dashboard")
        print("2. Select your domain")
        print("3. Find Zone ID in the right sidebar")
        sys.exit(1)
    
    # Initialize and run
    ddns = CloudflareDDNS(
        CONFIG['CF_API_TOKEN'],
        CONFIG['CF_ZONE_ID'],
        CONFIG['CF_RECORD_NAME']
    )
    
    # Run initial check
    ddns.check_and_update()
    
    # Start monitoring loop
    ddns.run_monitor()


if __name__ == '__main__':
    main()
