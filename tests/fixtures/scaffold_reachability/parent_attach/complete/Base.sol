// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./ParentVault.sol";

contract ExistingBase {
    ParentVault internal parentRef;

    function setUp() public {
        parentRef = new ParentVault();
    }
}
