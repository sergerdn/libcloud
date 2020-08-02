#!/usr/bin/env python
#
#  Licensed to the Apache Software Foundation (ASF) under one
#  or more contributor license agreements.  See the NOTICE file
#  distributed with this work for additional information
#  regarding copyright ownership.  The ASF licenses this file
#  to you under the Apache License, Version 2.0 (the
#  "License"); you may not use this file except in compliance
#  with the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing,
#  software distributed under the License is distributed on an
#  "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#  KIND, either express or implied.  See the License for the
#  specific language governing permissions and limitations
#  under the License.

import os
import re
import json
import copy
import time
from collections import defaultdict, OrderedDict

import requests
import demjson  # pylint: disable=import-error

LINUX_PRICING_URLS = [
    # Deprecated instances (JSON format)
    'https://aws.amazon.com/ec2/pricing/json/linux-od.json',
    # Previous generation instances (JavaScript file)
    'https://a0.awsstatic.com/pricing/1/ec2/previous-generation/linux-od.min.js',
    # New generation instances (JavaScript file)
    # Using other endpoint atm
    # 'https://a0.awsstatic.com/pricing/1/ec2/linux-od.min.js'
]

EC2_REGIONS = [
    'us-east-1',
    'us-east-2',
    'us-west-1',
    'us-west-2',
    'us-gov-west-1',
    'eu-west-1',
    'eu-west-2',
    'eu-west-3',
    'eu-north-1',
    'eu-central-1',
    'ca-central-1',
    'ap-southeast-1',
    'ap-southeast-2',
    'ap-northeast-1',
    'ap-northeast-2',
    'ap-south-1',
    'sa-east-1',
    'cn-north-1',
]

INSTANCE_SIZES = [
    'micro',
    'small',
    'medium',
    'large',
    'xlarge',
    'x-large',
    'extra-large'
]

RE_NUMERIC_OTHER = re.compile(r'(?:([0-9]+)|([-A-Z_a-z]+)|([^-0-9A-Z_a-z]+))')

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
PRICING_FILE_PATH = os.path.join(BASE_PATH, '../libcloud/data/pricing.json')
PRICING_FILE_PATH = os.path.abspath(PRICING_FILE_PATH)


def scrape_ec2_pricing():
    result = defaultdict(OrderedDict)
    os_map = {'linux': 'ec2_linux', 'windows-std': 'ec2_windows'}
    for item in os_map.values():
        result[item] = {}
    for url in LINUX_PRICING_URLS:
        response = requests.get(url)

        if re.match(r'.*?\.json$', url):
            data = response.json()
        elif re.match(r'.*?\.js$', url):
            data = response.content.decode()
            match = re.match(r'^.*callback\((.*?)\);?$', data,
                             re.MULTILINE | re.DOTALL)
            data = match.group(1)
            # demjson supports non-strict mode and can parse unquoted objects
            data = demjson.decode(data)
        regions = data['config']['regions']

        for region_data in regions:
            region_name = region_data['region']
            instance_types = region_data['instanceTypes']

            for instance_type in instance_types:
                sizes = instance_type['sizes']
                for size in sizes:
                    if not result['ec2_linux'].get(size['size'], False):
                        result['ec2_linux'][size['size']] = {}
                    price = size['valueColumns'][0]['prices']['USD']
                    if str(price).lower() == 'n/a':
                        # Price not available
                        continue

                    result['ec2_linux'][size['size']][
                        region_name] = float(price)

    res = defaultdict(OrderedDict)
    url = ('https://calculator.aws/pricing/1.0/'
           'ec2/region/{}/ondemand/{}/index.json')
    instances = set()
    for OS in ['linux', 'windows-std']:
        res[os_map[OS]] = {}
        for region in EC2_REGIONS:
            res[os_map[OS]][region] = {}
            response = requests.get(url.format(region, OS))
            if response.status_code != 200:
                continue
            data = response.json()

            for entry in data['prices']:
                instance_type = entry['attributes'].get(
                    'aws:ec2:instanceType', "")
                instances.add(instance_type)
                price = entry['price'].get('USD', 0)
                res[os_map[OS]][region][instance_type] = price
    for item in os_map.values():
        for instance in instances:
            if not result[item].get(instance, False):
                result[item][instance] = {}
            for region in EC2_REGIONS:
                if res[item][region].get(instance, False):
                    result[item][instance][region] = float(res[
                        item][region][instance])

    return result


def update_pricing_file(pricing_file_path, pricing_data):
    with open(pricing_file_path, 'r') as fp:
        content = fp.read()

    data = json.loads(content)
    original_data = copy.deepcopy(data)

    data['compute'].update(pricing_data)

    if data == original_data:
        # Nothing has changed, bail out early and don't update "updated" attribute
        print("Nothing has changed, skipping update.")
        return

    data['updated'] = int(time.time())

    # Always sort the pricing info
    data = sort_nested_dict(data)

    content = json.dumps(data, indent=4)
    lines = content.splitlines()
    lines = [line.rstrip() for line in lines]
    content = '\n'.join(lines)

    with open(pricing_file_path, 'w') as fp:
        fp.write(content)


def sort_nested_dict(value):
    """
    Recursively sort a nested dict.
    """
    result = OrderedDict()

    for key, value in sorted(value.items(), key=sort_key_by_numeric_other):
        if isinstance(value, (dict, OrderedDict)):
            result[key] = sort_nested_dict(value)
        else:
            result[key] = value

    return result


def sort_key_by_numeric_other(key_value):
    """
    Split key into numeric, alpha and other part and sort accordingly.
    """
    result = []

    for (numeric, alpha, other) in RE_NUMERIC_OTHER.findall(key_value[0]):
        numeric = int(numeric) if numeric else -1
        alpha = INSTANCE_SIZES.index(alpha) if alpha in INSTANCE_SIZES else alpha
        alpha = str(alpha)
        item = tuple([numeric, alpha, other])
        result.append(item)

    return tuple(result)


def main():
    print('Scraping EC2 pricing data (this may take up to 2 minutes)....')

    pricing_data = scrape_ec2_pricing()
    update_pricing_file(pricing_file_path=PRICING_FILE_PATH,
                        pricing_data=pricing_data)

    print('Pricing data updated')


if __name__ == '__main__':
    main()
