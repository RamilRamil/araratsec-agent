// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Parent {
    uint256 private hidden;
    uint256 internal visibleInternal;
}

contract Leaf is Parent {
    uint256 public leafOnly;
}
