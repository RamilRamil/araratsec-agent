// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "./Grandparent.sol";

contract Parent is Grandparent {
    uint256 public parentAsset;

    function setUp() public {}
}
