import boto3
import logging
from netaddr import IPNetwork, cidr_merge, cidr_exclude, IPAddress
import ipaddress
from faker import Faker
import itertools

dynamodbTableName = "dev_vpc_cidr"
dynamodb = boto3.resource('dynamodb')


iad_platform = "iad"
iad_region = "na"
iad_environment = "dev"
vpc_masks = 8
log_level = "DEBUG"


iad_id = "{0}/{1}/{2}".format(iad_platform, iad_region, iad_environment)

def get_logger(name, logging_level):
    levels = {
        "NOTSET": logging.NOTSET,
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    logger = logging.getLogger(name=name)
    logger.setLevel(levels[logging_level])

    return logger

log = get_logger("cidr_managment", log_level)

#############################################################
def closest(lst, prefix):
        suitable_prefix = next((i for i in lst if prefix >= i), None)
        if suitable_prefix == None:
            raise Exception("Cannot find free network for prefix: {0}".format(prefix))
        return suitable_prefix

# Getting all value from 'vpc_cidr' filed in DynamoDB. 
def getCidrDDB(dynamodbTableName):
    table = dynamodb.Table(dynamodbTableName)
    cidrs = table.scan()['Items']
    list_of_cidr = []
    for _ in cidrs: 
        list_of_cidr.append(_['vpc_cidr'])
    return list_of_cidr

#Generate random CIDR
def GeneratorRandomCidr(dynamodbTableName, vpc_masks):
    fake = Faker()
    vpc_cidr = str(IPNetwork(fake.ipv4_private()+'/{0}'.format(vpc_masks)).cidr)
    while vpc_cidr in getCidrDDB(dynamodbTableName):
        vpc_cidr = str(IPNetwork(fake.ipv4_private()+'/{0}'.format(vpc_masks)).cidr)
    return vpc_cidr

# Check if IP belongs to the network
def vpc_exists(dynamodbTableName, iad_id):
    try:
        table = dynamodb.Table(dynamodbTableName)
        item = table.get_item(Key={'iad_id': iad_id})['Item']
        return item
    except Exception as ex:
        return None


class IPSplitter():
    def __init__(self, vpc_cidr, used_subnets = []):
        self.availible_subnets = set((IPNetwork(vpc_cidr),))
        self.used_subnets = cidr_merge(used_subnets) 
    def get_free_subnets(self):
    # Calculate free subnets in existing VPC. 
    # Return is a list: [IPNetwork('192.168.0.0/30'), IPNetwork('192.168.0.16/28')]
        for ip_network in self.availible_subnets:
           self.availible_subnets = list(cidr_exclude(ip_network, self.used_subnets[0]))
        for used in self.used_subnets: 
            for free in list(self.availible_subnets):
                if IPNetwork(used) in IPNetwork(free):
                    self.availible_subnets.remove(free)
                    self.availible_subnets = self.availible_subnets + cidr_exclude(free,used)
        return self.availible_subnets

    def get_subnet(self, prefix):
        self.get_free_subnets()
    # Finding suitable subnets (by the closest prefix), splitting getting subnets
    # Return all prefix of free subnet: [30, 29, 28]
        free_subnets_prefix = [ _.prefixlen for _ in self.availible_subnets ]
    ## Return max prefix of suit subnets: 28
        max_suit_prefix = closest(free_subnets_prefix, prefix)
    ## Return suit free subnet: 192.168.0.16/28
        cidr = self.availible_subnets[free_subnets_prefix.index(max_suit_prefix)]
    ## Remove suit free cidr
        self.availible_subnets.remove(cidr)
    ## Getting suit subnets 
        subnet = list(cidr.subnet(prefix, count = 1))
    ## Exlude subnet, and add free subnets to list "self.availible_subnets"
        self.availible_subnets = self.availible_subnets + cidr_exclude(cidr,subnet[0])
        return subnet

#vpc1 = IPSplitter(vpc_cidr,active_subnets)
#vpc1.get_free_subnets()
#print(vpc1.get_subnet(30))
#print(vpc1.get_subnet(30))

input_private_cidrs = ["/31","/31","/31"]
input_public_cidr = ["/31","/31", "/32"]

public_cidrs = ['192.168.0.0/31', '192.168.0.2/31']
private_cidr = ['192.168.0.4/31', '192.168.0.6/31', '192.168.0.8/31']
def discover_new_subnets(used_subnet, desired_subnet):
    print()

##########
# STEP 1 #
##########
# if vpc exist in DynamoDB, otherwise will create
if vpc_exists(dynamodbTableName, iad_id):
    vpc_network = vpc_exists(dynamodbTableName, iad_id)
    vpc_cidr = vpc_network['vpc_cidr']
    database_cidrs = vpc_network.get('database_subnets', list())
    private_cidrs = vpc_network.get('private_subnets', list())
    public_cidrs = vpc_network.get('public_subnets', list())
    dmz_cidrs = vpc_network.get('dmz_subnets', list())
    used_subnets = database_cidrs + private_cidrs + public_cidrs + dmz_cidrs

# Find diff between existing subnet and new
    print(private_cidrs)
    print(public_cidrs)
#    vpc = IPSplitter(vpc_cidr, used_subnets)

else:
    vpc_cidr = GeneratorRandomCidr(dynamodbTableName, vpc_masks)

#class IPSplitter():
#    def __init__(self, vpc_cidr):
#        self.avail_ranges = set((IPNetwork(vpc_cidr),))
#
#    def get_subnet(self, prefix, count=2):
#        for ip_network in self.avail_ranges:
#            subnets = list(ip_network.subnet(prefix, count=count))
#            if not subnets:
#                continue
#            self.remove_avail_range(ip_network)
#            self.avail_ranges = self.avail_ranges.union(set(cidr_exclude(ip_network, cidr_merge(subnets)[0])))
#            return subnets
#
#    def get_available_ranges(self):
#        return self.avail_ranges
#
#    def remove_avail_range(self, ip_network):
#        self.avail_ranges.remove(ip_network)



#def put_item(dynamodbTableName):
#    dynamodb = boto3.resource('dynamodb')
#    table = dynamodb.Table(dynamodbTableName)
#    item = table.put_item(
#        Item={
#            'cidr': "192.168.0.0/16",
#            'private_subnet': {
#                '192.168.0.0/19',
#                '192.168.32.0/19'
#            },
#            'public_subnet': {
#                '192.168.128.0/19',
#                '192.168.160.0/19'
#            },
#
#        }
#    )
#    return item


#print(vpc.get_available_ranges())


##a = cidr_exclude(networks, IPNetwork(
#print(list(networks.subnet(30,2)))
#
#for i in networks:
#    print("availible: {0}".format(i))
#
#def get_item(dynamodbTableName):
#    dynamodb = boto3.resource('dynamodb')
#    table = dynamodb.Table(dynamodbTableName)
#    item = table.get_item(Key={'cidr':'192.168.0.0/16'})['Item']
#    return item
#

