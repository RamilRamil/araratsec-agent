// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {RealParent as P} from "./RealParent.sol";

contract Leaf is P {
    uint256 public leafOnly;
}
