// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract RoleVault {
    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR");

    function privileged() external pure {
        // require(hasRole(OPERATOR_ROLE, msg.sender));
    }
}
