// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "./Parent.sol";

contract Leaf is Parent {
    uint256 public leafOnly;
}
