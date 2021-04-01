import boto3
import ipaddress
import json
import math
from netaddr import IPNetwork
from faker import Faker


dynamodbTableName = "vpc_cidr"
dynamodb = boto3.resource('dynamodb')

def getCidrDDB(dynamodbTableName):

    # Vpc_cidr is the table name here
    table = dynamodb.Table(dynamodbTableName)
    # Table scan
    cidrs = table.scan()['Items']
    list_of_cidr = []
    for _ in cidrs: 
        list_of_cidr.append(_['cidr'])
    return list_of_cidr

def CidrSplitter(network, count):
    #Get smallest power of 2 greater than (or equal to) a given x. 
    def power_log(x):
        return 2**(math.ceil(math.log(x, 2)))
    #Newton's method for calculating square roots.
    def isqrt(n):
        x = n
        y = (x + 1) // 2
        while y < x:
            x = y
            y = (x + n // x) // 2
        return x
    # Get the main network, to divide onto predefined parts
    pair = ipaddress.ip_network(network, strict=False)
    # Get the require number of subnets to which the network will be divided
    parts = count
    # Extracting netmask of the main network in CIDR
    prefix = pair.prefixlen
    # Awareness of subnets' prefix, to divide main network onto
    subnet_diff = isqrt(power_log(float(parts)))
    # Get subnets of the main network, as a list
    subnets = list(pair.subnets(prefixlen_diff=subnet_diff))
    return subnets
print(CidrSplitter("10.5.0.0/16",2))

def GeneratorRandomCidr(netmask):
    fake = Faker()
    return str(IPNetwork(fake.ipv4_private()+'/{0}'.format(netmask)).cidr)

