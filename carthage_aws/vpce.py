import asyncio
import time

from carthage import *
from carthage.dependency_injection import *
from carthage.utils import memoproperty
from carthage_aws.connection import AwsConnection, AwsClientManaged, run_in_executor
from carthage_aws.network import AwsVirtualPrivateCloud, AwsSubnet
from carthage_aws.elbv2 import AwsLoadBalancer

from dataclasses import dataclass, field

from .utils import unpack

from botocore.exceptions import ClientError

__all__ = ['AwsVpcEndpointService', 'AwsVpcEndpoint']

@inject_autokwargs(vpc=AwsVirtualPrivateCloud, lb=AwsLoadBalancer)
class AwsVpcEndpointService(AwsClientManaged):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = None

    resource_type = 'vpc_endpoint_service'

    def find_from_id(self):
        try:
            r = self.client.describe_vpc_endpoint_service_configurations(ServiceIds=[self.id])
            self.cache = unpack(r['ServiceConfigurations'][0])
        except ClientError as e:
            logger.warning(f'Failed to load {self}', exc_info=e)
            self.cache = None
            if not self.readonly:
                self.connection.invalid_ec2_resource(self.resource_type, self.id, name=self.name)
            return
        return self.cache

    def do_create(self):
        r = self.client.create_vpc_endpoint_service_configuration(
            AcceptanceRequired=False,
            GatewayLoadBalancerArns=[self.lb.arn],
            TagSpecifications=[self.resource_tags]
        )
        r = r['ServiceConfiguration']
        self.cache = unpack(r)
        self.id = self.cache.ServiceId
        return self.cache

@inject_autokwargs(vpcsvc=InjectionKey(AwsVpcEndpointService, _optional=True))
class AwsVpcEndpoint(AwsClientManaged):
    def __init__(self, **kwargs):
        if 'endpoint_type' in kwargs:
            self.endpoint_type = kwargs.pop('endpoint_type')
        else:
            self.endpoint_type = 'GatewayLoadBalancer'
        if 'vpc_id' in kwargs:
            self.vpc_id = kwargs.pop('vpc_id')
        if 'service_name' in kwargs:
            self.service_name = kwargs.pop('service_name')
        if ('subnet' in kwargs) and ('subnets' in kwargs):
            raise ValueError(f"call to AwsVpcEndpoint should not specify both 'subnet' and 'subnets'")
        elif ('subnet' in kwargs):
            self.subnets = [kwargs.pop('subnet')]
        elif ('subnets' in kwargs):
            self.subnets = kwargs.pop('subnets')
        else:
            self.subnets = False
        super().__init__(**kwargs)
        self.id = None

    resource_type = 'vpc_endpoint'

    @property
    def private_ipv4_address(self):
        return self.interface.PrivateIpAddress


    def do_create(self):

        kwargs = dict(
            VpcEndpointType=self.endpoint_type,
            TagSpecifications=[self.resource_tags]
        )
        if self.endpoint_type in ['Interface', 'GatewayLoadBalancer']:
            kwargs.update(dict(SubnetIds=[x.id for x in self.subnets]))

        if self.vpcsvc:
            kwargs.update(dict(VpcId=self.vpcsvc.vpc.id))
            kwargs.update(dict(ServiceName=self.vpcsvc.cache.ServiceName))
        else:
            kwargs.update(dict(VpcId=self.vpc_id.id))
            kwargs.update(dict(ServiceName=self.name))

        r = self.client.create_vpc_endpoint(**kwargs)

        r = r['VpcEndpoint']
        self.cache = unpack(r)
        self.id = self.cache.VpcEndpointId
        return self.cache

    def find_from_id(self):
        time.sleep(2)
        r = super().find_from_id()
        # FIXME
        # should we wait here?
        if self.endpoint_type != 'Gateway':
            try:
                self.interface = unpack(self.client.describe_network_interfaces(NetworkInterfaceIds=[self.cache.NetworkInterfaceIds[0]])['NetworkInterfaces'][0])
            except Exception as e:
                breakpoint()
                raise e
        return r

    async def post_find_hook(self):
        while True:
            state = self.client.describe_vpc_endpoints(VpcEndpointIds=[self.id])['VpcEndpoints'][0]['State']
            if state == 'available': break
            print(f'waiting on vpce: {self}')
            await asyncio.sleep(5)