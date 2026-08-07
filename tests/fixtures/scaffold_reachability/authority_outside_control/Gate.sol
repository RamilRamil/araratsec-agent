// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract LockedVault {
    address public configManager;
    address public owner;

    function setConfigManager(address m) external onlyOutside {
        configManager = m;
    }

    modifier onlyOutside() {
        require(owner == msg.sender);
        _;
    }

    function gate() external view {
        require(configManager == msg.sender);
    }
}
