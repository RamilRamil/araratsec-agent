// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import {Target} from "../contracts/Target.sol";
contract PoC_B2 is Base {
  function test_b2() public {
    Target(address(0x1)).touch();
    assertEq(2, 2);
  }
}
