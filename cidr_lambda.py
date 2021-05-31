import add_deps_path
import boto3
from netaddr import IPNetwork, cidr_merge, cidr_exclude, IPAddress
import ipaddress
from faker import Faker
import re
import itertools
import os

dynamodbTableName = os.environ["DYNAMODB_TABLE_NAME"]

# Find Suit subnet in order to split
def closest(lst, prefix):
    suitable_prefix = next((i for i in sorted(lst, reverse=True) if prefix >= i), None)
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
    return used_cidrs, new_prefix


class IPSplitter():
    def __init__(self, vpc_cidr, used_subnets=[]):
        self.availible_subnets = set((IPNetwork(vpc_cidr),))
        self.used_subnets = cidr_merge(used_subnets)
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

    def GetFreeRanges(self):
        return sorted(self.availible_subnets, key=lambda x: x.prefixlen, reverse=True)

    # Finding suitable subnets (by the closest prefix), splitting getting subnets
    def GetSubnet(self, prefix):
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
    def __init__(self, DynamoTableName, iad_id = ""):
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

    def DeleteItemDDB(self):
        response = self.table.delete_item(
            Key={
                'iad_id' : self.iad_id
            })

def main(dynamodbTableName, event):
    # Parsing event
    iad_id = event['iad_id']
    vpc_mask = int(event['vpc_mask'][1:]) if event['vpc_mask'] else event['vpc_mask']
    vpc_cidr_block = event['vpc_cidr_block'] if event['vpc_cidr_block'] else event['vpc_cidr_block']

    input_public = eval(event['public'])
    input_private = eval(event['private'])
    input_database = eval(event['database'])
    input_dmz = eval(event['dmz'])

    # Basic input validation
    if event['vpc_mask'] and event['vpc_mask'][0] != '/':
        raise Exception("Invalid VPC mask")
        subnets = input_public + input_private + input_database + input_dmz
        for _ in subnets:
            if _[0] != '/':
                raise Exception("Invalid subnets mask")

    db = DynamoDB(dynamodbTableName, iad_id)
    if db.VpcExists():
        vpc_network = db.VpcExists()
        vpc_cidr = vpc_network['vpc_cidr']

        # If the netmask is equal to the input mask (from event)
        if vpc_mask == int(re.search('\/(.*)', vpc_cidr).group(0)[1:]):
            database_cidrs = vpc_network.get('database_subnets', list())
            private_cidrs = vpc_network.get('private_subnets', list())
            public_cidrs = vpc_network.get('public_subnets', list())
            dmz_cidrs = vpc_network.get('dmz_subnets', list())
            used_subnets = database_cidrs + private_cidrs + public_cidrs + dmz_cidrs
            # Find diff between existing subnet and new
            public_cidrs, new_public_mask = discover_new_subnets(
                public_cidrs, input_public)
            private_cidrs, new_private_mask = discover_new_subnets(
                private_cidrs, input_private)
            database_cidrs, new_database_mask = discover_new_subnets(
                database_cidrs, input_database)
            dmz_cidrs, new_dmz_mask = discover_new_subnets(
                dmz_cidrs, input_dmz)
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
            # If new mask differ from current. Will created new VPC range
            if vpc_mask:
                vpc_cidr = GeneratorRandomCidr(vpc_mask, db.GetAllVpc())
                vpc = IPSplitter(vpc_cidr)
                public_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_public]
                private_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_private]
                database_cidrs = [vpc.GetSubnet(int(_[1:]))
                                  for _ in input_database]
                dmz_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_dmz]
                db.UpdateItemsDDB('vpc_cidr', vpc_cidr)
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
            # If the input VPC is managed manually through tfvars file
            elif vpc_cidr_block:
                db.UpdateItemsDDB('vpc_cidr', vpc_cidr_block)
                db.UpdateItemsDDB('public_subnets', input_public)
                db.UpdateItemsDDB('private_subnets', input_private)
                db.UpdateItemsDDB('database_subnets', input_database)
                db.UpdateItemsDDB('dmz_subnets', input_dmz)
                return { 
                    'vpc_cidr': vpc_cidr_block,
                    'public_subnets': input_public,
                    'private_subnets': input_private,
                    'database_subnets': input_database,
                    'dmz_subnets': input_dmz
                }
    else:
        # If the network is new
        if vpc_mask:
            vpc_cidr = GeneratorRandomCidr(vpc_mask, db.GetAllVpc())
            vpc = IPSplitter(vpc_cidr)
            public_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_public]
            private_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_private]
            database_cidrs = [vpc.GetSubnet(int(_[1:]))
                          for _ in input_database]
            dmz_cidrs = [vpc.GetSubnet(int(_[1:])) for _ in input_dmz]
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

        #  If the input VPC is managed manually through tfvars file
        elif vpc_cidr_block:
            content_of_item = {
                'iad_id': iad_id,
                'vpc_cidr': vpc_cidr_block,
                'public_subnets': input_public,
                'private_subnets': input_private,
                'database_subnets': input_database,
                'dmz_subnets': input_dmz
             }
            db.CreateItemsDDB(content_of_item)
            return { 
                'vpc_cidr': vpc_cidr_block,
                'public_subnets': input_public,
                'private_subnets': input_private,
                'database_subnets': input_database,
                'dmz_subnets': input_dmz
            }

def lambda_handler(event, context):
    if event["state"] == "register":
        return main(dynamodbTableName, event)

    elif event["state"] == "deregister":
        db = DynamoDB(dynamodbTableName, event["iad_id"]).DeleteItemDDB()
        return event["iad_id"]
    elif event["state"] == "get_vpc":
        db = DynamoDB(dynamodbTableName)
        vpc_cidr = GeneratorRandomCidr(event['vpc_mask'][1:], db.GetAllVpc())
        return vpc_cidr
#event = {
#    "state"          : "register",
#    "iad_id"         : "iad/apac/dev_iad",
#    "vpc_cidr_block" : "172.0.0.0/8",
#    "vpc_mask"       : "",
#    "public"         : "[]",
#    "private"        : "[]",
#    "database"       : "[]",
#    "dmz"            : "[]"
#}

#event = {
#    "state"          : "register",
#    "iad_id"         : "iad/na/dev",
#    "vpc_mask"       : "/28",
#    "vpc_cidr_block" : "",
#    "public"         : "['/30','/30']",
#    "private"        : "['/30']",
#    "database"       : "['/30']",
#    "dmz"            : "[]"
#}
#
#event = { 
#    "state" : "deregister",
#    "iad_id" : "iad/na/dev"
#}
#event = { 
#    "state"    : "get_vpc",
#    "vpc_mask" : "/28"
#}