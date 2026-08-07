// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./ParentVault.sol";
import "./Dep.sol";

contract SynthBase {
    ParentVault parentRef;

    function setUp() public {
        parentRef = new ParentVault();
        Dep d = new Dep();
        // missing parentRef.setDep(d);
    }
}
