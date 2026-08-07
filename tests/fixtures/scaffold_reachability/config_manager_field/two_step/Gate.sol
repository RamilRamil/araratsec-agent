// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract DemoVault {
    address public configManager;
    address public pendingManager;

    function proposeConfigManager(address m) external {
        pendingManager = m;
    }

    function executeConfigManager() external {
        configManager = pendingManager;
    }

    function gate() external view {
        require(configManager == msg.sender);
    }
}
