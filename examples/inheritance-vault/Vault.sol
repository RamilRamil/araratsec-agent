// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Base holds the shared `balances` state.
contract Base {
    mapping(address => uint256) public balances;

    function _credit(address user, uint256 amount) internal {
        balances[user] += amount;
    }
}

/// @notice Vault inherits Base and writes the inherited `balances` in withdraw.
/// withdraw() and the inherited _credit() (called by deposit) share state across
/// the inheritance boundary — a cross-contract interference the single-file
/// regex SIG cannot see.
contract Vault is Base {
    function deposit() external payable {
        _credit(msg.sender, msg.value);
    }

    function withdraw(uint256 amount) external {
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        balances[msg.sender] -= amount; // external call before state update
    }
}
