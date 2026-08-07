// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./Dep.sol";

contract ParentVault {
    Dep public dep;

    function setDep(Dep d) external {
        dep = d;
    }

    function reachThrough() external view returns (uint256) {
        return dep.value();
    }
}
