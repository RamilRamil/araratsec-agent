// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract RoleVault {
    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR");
    mapping(bytes32 => mapping(address => bool)) public roles;

    function grantRole(bytes32 role, address account) external {
        roles[role][account] = true;
    }

    function hasRole(bytes32 role, address account) public view returns (bool) {
        return roles[role][account];
    }

    function privileged() external view {
        require(hasRole(OPERATOR_ROLE, msg.sender));
    }
}
