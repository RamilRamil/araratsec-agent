// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract CooldownVault {
    address public configManager;

    function setConfigManager(address m) external {
        configManager = m;
    }

    function setVaultBounds(uint256 a, uint256 b) external view {
        require(configManager == msg.sender);
    }
}
