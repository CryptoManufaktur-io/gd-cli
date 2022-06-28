import math
from functools import cached_property
from typing import List, Set

import click
from eth_typing import ChecksumAddress, HexStr
from eth_utils import add_0x_prefix
from py_ecc.bls import G2ProofOfPossession
from web3 import Web3

from stakewise_cli.encoder import Encoder
from stakewise_cli.eth1 import get_operator_deposit_data_ipfs_link
from stakewise_cli.eth2 import get_mnemonic_signing_key
from stakewise_cli.ipfs import ipfs_fetch
from stakewise_cli.queries import get_stakewise_gql_client
from stakewise_cli.settings import IS_LEGACY
from stakewise_cli.typings import DatabaseKeyRecord
from stakewise_cli.utils import bytes_to_str


class Web3SignerManager:
    def __init__(
        self,
        operator: ChecksumAddress,
        network: str,
        mnemonic: str,
        validator_capacity: int,
    ):
        self.sw_gql_client = get_stakewise_gql_client(network)
        self.network = network
        self.mnemonic = mnemonic
        self.validator_capacity = validator_capacity
        self.operator_address = operator
        self.encoder = Encoder()

    @cached_property
    def keys(self) -> List[DatabaseKeyRecord]:
        """
        Returns prepared database key records from the latest deposit data or already registered.
        """
        deposit_data_key_records: List[DatabaseKeyRecord] = list()
        other_key_records: List[DatabaseKeyRecord] = list()

        keys_count = len(self.operator_deposit_data_public_keys)
        index = 0
        with click.progressbar(
            length=keys_count,
            label="Syncing key pairs\t\t",
            show_percent=False,
            show_pos=True,
        ) as bar:
            while len(deposit_data_key_records) < keys_count:
                curr_progress = len(deposit_data_key_records)

                signing_key = get_mnemonic_signing_key(self.mnemonic, index, IS_LEGACY)
                public_key = Web3.toHex(G2ProofOfPossession.SkToPk(signing_key.key))
                public_key = add_0x_prefix(public_key)

                private_key = str(signing_key.key)
                encrypted_private_key, nonce = self.encoder.encrypt(private_key)

                key_record = DatabaseKeyRecord(
                    public_key=public_key,
                    private_key=bytes_to_str(encrypted_private_key),
                    nonce=bytes_to_str(nonce),
                    validator_index=index // self.validator_capacity,
                )

                if public_key in self.operator_deposit_data_public_keys:
                    if key_record not in deposit_data_key_records:
                        deposit_data_key_records.append(key_record)
                    bar.update(len(deposit_data_key_records) - curr_progress)
                else:
                    if key_record not in other_key_records:
                        other_key_records.append(key_record)

                index += 1

        return other_key_records + deposit_data_key_records

    @cached_property
    def validators_count(self) -> int:
        return math.ceil(len(self.keys) / self.validator_capacity)

    @cached_property
    def deposit_data_ipfs_link(self) -> str:
        return get_operator_deposit_data_ipfs_link(
            self.sw_gql_client, self.operator_address
        )

    @cached_property
    def operator_deposit_data_public_keys(self) -> Set[HexStr]:
        """Returns operator's deposit data public keys."""

        result: Set[HexStr] = set()
        if not self.deposit_data_ipfs_link:
            return result

        deposit_datum = ipfs_fetch(self.deposit_data_ipfs_link)
        for deposit_data in deposit_datum:
            public_key = deposit_data["public_key"]
            if public_key in result:
                raise click.ClickException(
                    f"Public key {public_key} is presented twice in {self.deposit_data_ipfs_link}"
                )
            result.add(public_key)

        return result
