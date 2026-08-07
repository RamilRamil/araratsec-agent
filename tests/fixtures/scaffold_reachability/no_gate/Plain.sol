// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract PlainVault {
    uint256 public value;

    function bump() external {
        value += 1;
    }
}
