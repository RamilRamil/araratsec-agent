// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./Gate.sol";

contract SynthBase {
    DemoVault vault;

    function setUp() public {
        vault = new DemoVault();
        vault.setConfigManager(address(this));
        // may later call vault.gate()
    }
}
