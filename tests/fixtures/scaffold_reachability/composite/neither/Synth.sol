// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./ParentVault.sol";
import "./CooldownVault.sol";

contract SynthBase {
    ParentVault parentRef;

    function setUp() public {
        parentRef = new ParentVault();
        CooldownVault c = new CooldownVault();
        // neither setConfigManager nor setCooldown
    }
}
