# Copyright (C) 2022, Hadron Industries, Inc.
# Carthage is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License version 3
# as published by the Free Software Foundation. It is distributed
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the file
# LICENSE for details.
from carthage import *
from carthage.dependency_injection import *
from carthage.network import TechnologySpecificNetwork, this_network
from carthage.config import ConfigLayout
from carthage.modeling import NetworkModel

from .connection import AwsClientManaged, run_in_executor
from .transit import AwsTransitGateway, AwsTransitGatewayVpnAttachment
from .utils import unpack

from xmltodict import parse

import boto3
from botocore.exceptions import ClientError

__all__ = [
    'AwsCustomerGateway',
    'AwsVpnConnection'
]

class AwsCustomerGateway(AwsClientManaged):

    resource_type = 'customer_gateway'

    def __init__(self, name, public_ipv4, asn=65000, **kwargs):
        super().__init__(**kwargs)
        self.asn = asn
        self.name = name
        self.public_ipv4 = public_ipv4

    def do_create(self):
        r = self.client.create_customer_gateway(
            BgpAsn=int(self.asn),
            PublicIp=self.public_ipv4,
            Type='ipsec.1',
            TagSpecifications=[self.resource_tags],
            DeviceName=self.name,
        )['CustomerGateway']
        self.cache = unpack(r)
        return self.cache

class AwsVpnGateway(AwsClientManaged):

    resource_type = 'vpn_gateway'

    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)

    def do_create(self):
        r = self.client.create_vpn_gateway(
            AvailabilityZone=self.availability_zone,
            Type='ipsec.1',
            TagSpecifications=[self.resource_tags],
            AmazonSideAsn=123
        )
        self.cache = unpack(r)
        return self.cache

@inject_autokwargs(tgw=AwsTransitGateway, cust_gw=AwsCustomerGateway)
class AwsVpnConnection(AwsClientManaged):
    
    resource_type = 'vpn_connection'

    okw = ['TunnelInsideCidr', 'TunnelInsideIpv6Cidr', 'PreSharedKey', 'Phase1LifetimeSeconds',
            'Phase2LifetimeSeconds', 'RekeyMarginTimeSeconds', 'RekeyFuzzPercentage', 'ReplayWindowSize',
            'DPDTimeoutSeconds', 'DPDTimeoutAction']

    oda = ['Phase1EncryptionAlgorithms', 'Phase2EncryptionAlgorithms', 'Phase1IntegrityAlgorithms',
            'Phase2IntegrityAlgorithms', 'Phase1DHGroupNumbers', 'Phase2DHGroupNumbers', 'IKEVersions']

    def __init__(self, **kwargs):
        self.kwopts = {}
        for kw in self.okw:
            if kw in kwargs:
                self.kwopts[kw] = kwargs.pop(kw)
        for kw in self.oda:
            if kw in kwargs:
                k = kwargs.pop(kw)
                if type(k) is list:
                    k = [ dict(Value=x) for x in k ]
                else:
                    k = [ dict(Value=k) ]
                self.kwopts[kw] = k
        super().__init__(**kwargs)

    def do_create(self):
        options = {
           'EnableAcceleration':False,
           'StaticRoutesOnly':False,
           'TunnelInsideIpVersion':'ipv4'
        }
        if len(self.kwopts.keys()) > 0:
            options['TunnelOptions'] = [self.kwopts, self.kwopts]
        kwargs = {
            f'{self.tgw.resource_name}Id':self.tgw.id,
            'CustomerGatewayId':self.cust_gw.id,
            'Type':'ipsec.1',
            'TagSpecifications':[self.resource_tags]
        }
        kwargs['Options'] = options

        r = self.client.create_vpn_connection(**kwargs)['VpnConnection']
        self.cache = unpack(r)
        self.cust_info = unpack(parse(self.cache.CustomerGatewayConfiguration, dict_constructor=dict))
        return self.cache

    async def post_find_hook(self):
        r = await super().post_find_hook()
        self.cust_info = unpack(parse(self.cache.CustomerGatewayConfiguration, dict_constructor=dict))
        tgwat = [x for x in self.client.describe_transit_gateway_attachments()['TransitGatewayAttachments'] if x['ResourceId'] == self.id][0]
        self.tgwat = AwsTransitGatewayVpnAttachment(id=tgwat['TransitGatewayAttachmentId'])
        self.tgw.attachments[self.tgwat.id] = self.tgwat
        return r
