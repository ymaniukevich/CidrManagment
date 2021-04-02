import boto3
import ipaddress
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
    # Finding the minimum power of two 
    def power_of_two(count):
        if count > 1:
            for i in range(1, int(count)):
                if (2 ** i >= count):
                    return i
        else:
            return 1
    # Get the main network
    pair = ipaddress.ip_network(network, strict=False)
    
    # The subnet prefix to be added to the original to split the main network into
    subnet_diff = power_of_two(count)

    # Get subnets of the main network, as a list
    subnets = list(pair.subnets(prefixlen_diff=subnet_diff))
    subnet_map = {}
    for _ in range(0,count):
        subnet_map[_+1] = str(subnets[_])
    return {network:subnet_map}

def GeneratorRandomCidr(netmask):
    fake = Faker()
    return str(IPNetwork(fake.ipv4_private()+'/{0}'.format(netmask)).cidr)


def main(dynamodbTableName, netmask, subnet_count):
    # Generate cidr
    cidr = GeneratorRandomCidr(netmask)

    # Checking if cidr is not used
    while cidr in getCidrDDB(dynamodbTableName):
        cidr = GeneratorRandomCidr(netmask)
    return CidrSplitter(cidr, subnet_count)

print(main(dynamodbTableName,16,4))


