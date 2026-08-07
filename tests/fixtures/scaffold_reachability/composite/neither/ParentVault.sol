// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./CooldownVault.sol";

contract ParentVault {
    CooldownVault public cooldown;

    function setCooldown(CooldownVault c) external {
        cooldown = c;
    }

    function reach() external {
        cooldown.setVaultBounds(1, 2);
    }
}
