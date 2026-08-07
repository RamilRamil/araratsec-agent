// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./ParentA.sol";
import "./ParentB.sol";

contract ExistingBase {
    ParentA internal parentA;
    ParentB internal parentB;

    function setUp() public {
        parentA = new ParentA();
        parentB = new ParentB();
    }
}
