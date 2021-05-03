import boto3
import logging
from netaddr import IPNetwork, cidr_merge, cidr_exclude, IPAddress
import ipaddress
from faker import Faker
import re
import itertools
import time
import ast

dynamodb = 'dev_vpc_cidr'

# Find Suit subnet in order to split


def closest(lst, prefix):
    suitable_prefix = next((i for i in lst if prefix >= i), None)
    if suitable_prefix == None:
        raise Exception(
            "Cannot find free network for prefix: {0}".format(prefix))
    return suitable_prefix

# Generate random CIDR


def GeneratorRandomCidr(VpcMask, AllExistsVpc=[]):
    fake = Faker()
    vpc_cidr = str(IPNetwork(fake.ipv4_private() +
                             '/{0}'.format(VpcMask)).cidr)
    while vpc_cidr in AllExistsVpc:
        vpc_cidr = str(IPNetwork(fake.ipv4_private() +
                                 '/{0}'.format(VpcMask)).cidr)
    return vpc_cidr


def discover_new_subnets(used_cidrs, desired_public_cidr=[]):
    # The function compares used and desired prefix, if there are changes, the whole sequence will be removed.
    # 1. Used: ['/31', '/31', '/31'], desired = ['/31', '/31', '/31'] => No changes
    # 2. Used: ['/31', '/31', '/31'], desired = ['/31', '/32', '/31'] => New suqence is ['/32', '/31'] and only first subnet with no changes
    used_prefix = [re.search('\/(.*)', i).group(0) for i in used_cidrs]
    new_prefix = []
    count = -1
    for desired, used in itertools.zip_longest(desired_public_cidr, used_prefix):
        count += 1
        if desired != used and used != None:
            del used_cidrs[count:]
            new_prefix = desired_public_cidr[count:]
            break
        elif len(desired_public_cidr) > len(used_prefix):
            new_prefix = desired_public_cidr[len(used_prefix):]
            break
    new_prefix = [_[1:] for _ in new_prefix]
    print
    return used_cidrs, new_prefix


class IPSplitter():
    def __init__(self, vpc_cidr, used_subnets=[]):
        self.availible_subnets = set((IPNetwork(vpc_cidr),))
        self.used_subnets = cidr_merge(used_subnets)

    # Calculate free subnets in existing VPC.
    def GetFreeSubnets(self):
        # Return is a list: [IPNetwork('192.168.0.0/30'), IPNetwork('192.168.0.16/28')]
        if len(self.used_subnets) != 0:
            for ip_network in self.availible_subnets:
                self.availible_subnets = list(
                    cidr_exclude(ip_network, self.used_subnets[0]))
            for used in self.used_subnets:
                for free in list(self.availible_subnets):
                    if IPNetwork(used) in IPNetwork(free):
                        self.availible_subnets.remove(free)
                        self.availible_subnets = self.availible_subnets + \
                            cidr_exclude(free, used)
        else:
            self.availible_subnets = list(self.availible_subnets)
        return self.availible_subnets

    # Finding suitable subnets (by the closest prefix), splitting getting subnets
    def GetSubnet(self, prefix):
        self.GetFreeSubnets()
    # Return all prefix of free subnet: [30, 29, 28]
        free_subnets_prefix = [_.prefixlen for _ in self.availible_subnets]
    # Return max prefix of suit subnets: 28
        max_suit_prefix = closest(free_subnets_prefix, prefix)
    # Return suit free subnet: 192.168.0.16/28
        cidr = self.availible_subnets[free_subnets_prefix.index(
            max_suit_prefix)]
    # Remove suit free cidr
        self.availible_subnets.remove(cidr)
    # Getting suit subnets
        subnet = list(cidr.subnet(prefix, count=1))
    # Exlude subnet, and add free subnets to list "self.availible_subnets"
        self.availible_subnets = self.availible_subnets + \
            cidr_exclude(cidr, subnet[0])
        return str(subnet[0])


class DynamoDB():
    def __init__(self, DynamoTableName, iad_id):
        dynamodb = boto3.resource('dynamodb')
        self.table = dynamodb.Table(DynamoTableName)
        self.dynamodb_table_name = DynamoTableName
        self.iad_id = iad_id
    # Checking if an VPC exists in the DynamoDB by IAD tag

    def VpcExists(self):
        try:
            item = self.table.get_item(Key={'iad_id': self.iad_id})['Item']
            return item
        except Exception as ex:
            return None

    # Gathering all vpc in DynamoDB
    def GetAllVpc(self):
        items = self.table.scan()['Items']
        all_vpc = [vpc['vpc_cidr'] for vpc in items]
        return all_vpc

    # Updating VPC information
    def UpdateItemsDDB(self, subnet_name, lst_subnet):
        response = self.table.update_item(
            Key={
                'iad_id': self.iad_id,
            },
            UpdateExpression='SET {0} = :val1'.format(subnet_name),
            ExpressionAttributeValues={
                ':val1': lst_subnet
            }
        )
        return response
    # Creating Item in DynamoDB

    def CreateItemsDDB(self, new_item_content):
        response = self.table.put_item(
            Item=new_item_content
        )


def main(event, dynamodbTableName, iad_id, vpc_mask, input_public_masks, input_private_masks, input_database_masks, input_dmz_masks):
    db = DynamoDB(dynamodbTableName, iad_id)
    if db.VpcExists():
        vpc_network = db.VpcExists()
        vpc_cidr = vpc_network['vpc_cidr']
        database_cidrs = vpc_network.get('database_subnets', list())
        private_cidrs = vpc_network.get('private_subnets', list())
        public_cidrs = vpc_network.get('public_subnets', list())
        dmz_cidrs = vpc_network.get('dmz_subnets', list())
        used_subnets = database_cidrs + private_cidrs + public_cidrs + dmz_cidrs
# Find diff between existing subnet and new
        public_cidrs, new_public_mask = discover_new_subnets(
            public_cidrs, input_public_masks)
        private_cidrs, new_private_mask = discover_new_subnets(
            private_cidrs, input_private_masks)
        database_cidrs, new_database_mask = discover_new_subnets(
            database_cidrs, input_database_masks)
        dmz_cidrs, new_dmz_mask = discover_new_subnets(
            dmz_cidrs, input_dmz_masks)
# Getting new subnets cidr, and plus with old items
        vpc = IPSplitter(vpc_cidr, used_subnets)
        public_cidrs = public_cidrs + \
            [vpc.GetSubnet(int(_)) for _ in new_public_mask]
        private_cidrs = private_cidrs + \
            [vpc.GetSubnet(int(_)) for _ in new_private_mask]
        database_cidrs = database_cidrs + \
            [vpc.GetSubnet(int(_)) for _ in new_database_mask]
        dmz_cidrs = dmz_cidrs + [vpc.GetSubnet(int(_)) for _ in new_dmz_mask]
# Update DunamoDB table
        db.UpdateItemsDDB('public_subnets', public_cidrs)
        db.UpdateItemsDDB('private_subnets', private_cidrs)
        db.UpdateItemsDDB('database_subnets', database_cidrs)
        db.UpdateItemsDDB('dmz_subnets', dmz_cidrs)
        return { 
            'vpc_cidr': vpc_cidr,
            'public_subnets': public_cidrs,
            'private_subnets': private_cidrs,
            'database_subnets': database_cidrs,
            'dmz_subnets': dmz_cidrs
        }
    else:
        vpc_cidr = GeneratorRandomCidr(vpc_mask, db.GetAllVpc())
        vpc = IPSplitter(vpc_cidr)
        public_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_public_masks]
        private_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_private_masks]
        database_cidrs = [vpc.GetSubnet(int(_[1:]))
                          for _ in input_database_masks]
        dmz_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_dmz_masks]

        content_of_item = {
            'iad_id': iad_id,
            'vpc_cidr': vpc_cidr,
            'public_subnets': public_cidrs,
            'private_subnets': private_cidrs,
            'database_subnets': database_cidrs,
            'dmz_subnets': dmz_cidrs
        }

        db.CreateItemsDDB(content_of_item)

        return { 
            'vpc_cidr': vpc_cidr,
            'public_subnets': public_cidrs,
            'private_subnets': private_cidrs,
            'database_subnets': database_cidrs,
            'dmz_subnets': dmz_cidrs
        }

event = {
    "iad_id": "iad/na/dev5",
    "vpc_mask": "/16",
    "public": "['/31','/31','/31']",
    "private": "[]",
    "database": "[]",
    "dmz": "[]"
}


def lambda_handler(event):
    dynamodbTableName = 'dev_vpc_cidr'
    iad_id = event['iad_id']
    vpc_mask = int(event['vpc_mask'][1:])

    input_public_masks = ast.literal_eval(event['public'])
    input_private_masks = ast.literal_eval(event['private'])
    input_database_masks = ast.literal_eval(event['database'])
    input_dmz_masks = ast.literal_eval(event['dmz'])

    return main(event, dynamodbTableName, iad_id, vpc_mask, input_public_masks,
             input_private_masks, input_database_masks, input_dmz_masks)
