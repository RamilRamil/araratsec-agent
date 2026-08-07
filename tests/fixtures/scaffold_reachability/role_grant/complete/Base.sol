// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./Gate.sol";

contract ExistingBase {
    RoleVault vault;

    function setUp() public {
        vault = new RoleVault();
        vault.grantRole(vault.OPERATOR_ROLE(), address(this));
    }
}
