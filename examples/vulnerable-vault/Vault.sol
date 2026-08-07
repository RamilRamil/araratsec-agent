// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title Vault
/// @notice Deliberately vulnerable example for SR-agent testing.
/// @dev Contains a classic reentrancy in withdraw(): the external call
///      happens BEFORE the balance is updated (violates checks-effects-interactions).
contract Vault {
    mapping(address => uint256) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    /// @dev VULNERABLE: external call before state update -> reentrancy.
    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "insufficient balance");

        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");

        balances[msg.sender] -= amount; // state updated too late
    }

    function totalBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
