// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract DemoVault {
    address public configManager;

    function setConfigManager(address m) external {
        configManager = m;
    }

    function gate() external view {
        require(configManager == msg.sender);
    }
}
