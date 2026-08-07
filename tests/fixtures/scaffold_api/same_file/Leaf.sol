// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Parent {
    uint256 public parentAsset;
    uint256 private secret;

    function setUp() public {}

    function _deployThing(address a) internal {}
}

contract Leaf is Parent {
    uint256 public leafOnly;

    function _grantRole(bytes32 r, address a) internal {}
}
