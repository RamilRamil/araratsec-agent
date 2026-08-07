// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import {Target} from "../contracts/Target.sol";
contract PoC_A is Base {
  function test_a() public {
    Target(address(0x1)).touch();
    assertEq(1, 1);
  }
}
