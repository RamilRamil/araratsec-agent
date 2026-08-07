// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "./Twin.sol";

contract Parent {
    uint256 public sameFileAsset;

    function setUp() public {}
}

contract Leaf is Parent {
    uint256 public leafOnly;
}
