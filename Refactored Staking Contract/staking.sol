// SPDX-License-Identifier: MIT
pragma solidity 0.8.10;
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/* 
Refactored Staking Contract 
    1. Added the Support of Traditional & LP Staking 
    2. StakeToken & RewardToken can be the same or different
    3. Removed Unnecessary modifiers & ERC20 functions 
    4. Removed Unnecessary checks & library use e.g. safeMath

Refactored by Salman Haider, Senior Blockchain Architect @ Ferrum Network
*/

contract Staking {

/* 
   - Not using SafeMath since it is not needed for solidity versions > 0.8.0
        using SafeMath for uint256;
*/

    // map address to user stake
    mapping(address => uint256) stakes;
    //staking details
    address public stakeTokenAddress;
    address public rewardTokenAddress;
    uint256 public stakingStarts;
    uint256 public stakingEnds;
    uint256 public stakingTotal;
    uint256 public stakedTotal;
    uint256 public withdrawStarts;
    uint256 public withdrawEnds;
    uint256 public totalReward;
    uint256 public earlyWithdrawReward;
    uint256 public rewardBalance;
    uint256 public stakedBalance;

    IERC20 public ERC20Interface;

    event Staked(address indexed token, address indexed staker_, uint256 requestedAmount_, uint256 stakedAmount_);
    event PaidOut(
        address indexed stakeTokenAddress,
        address indexed rewardTokenAddress,
        address indexed staker_,
        uint256 amount_,
        uint256 reward_
    );
    event Refunded(address indexed token, address indexed staker_, uint256 amount_);

    constructor(
        address stakeTokenAddress_,
        address rewardTokenAddress_,
        uint256 stakingStarts_,
        uint256 stakingEnds_,
        uint256 withdrawStarts_,
        uint256 withdrawEnds_,
        uint256 stakingTotal_
    ) {
        require(stakeTokenAddress_ != address(0), "Festaking: 0 address");
        stakeTokenAddress = stakeTokenAddress_;

        require(rewardTokenAddress_ != address(0), "Festaking: 0 address");
        rewardTokenAddress = rewardTokenAddress_;

        require(stakingStarts_ > 0, "Festaking: zero staking start time");
        if (stakingStarts_ < block.timestamp) {
            stakingStarts = block.timestamp;
        } else {
            stakingStarts = stakingStarts_;
        }

        require(stakingEnds_ > stakingStarts, "Festaking: staking end must be after staking starts");
        stakingEnds = stakingEnds_;

        require(stakingTotal_ > 0, "Festaking: stakingTotal must be positive");
        stakingTotal = stakingTotal_;

        require(withdrawStarts_ >= stakingEnds, "Festaking: withdrawStarts must be after staking ends");
        withdrawStarts = withdrawStarts_;

        require(withdrawEnds_ > withdrawStarts, "Festaking: withdrawEnds must be after withdraw starts");
        withdrawEnds = withdrawEnds_;
    }

/*. NOT NEEDED 

    1. Redundant check since no msg.sender can never be 0 address.
        modifier _realAddress(address addr) {

            require(addr != address(0), "Festaking: zero address");
            _;
        }

    2. Incorrect check since uint can never be negative.
        Also, even if we were using int, our condition should have been amount > 0, not amount > 2.

        modifier _positive(uint256 amount) {
            require(amount > 2, "Festaking: negative amount");
            _;
        }
*/
    modifier _after(uint256 eventTime) {
        require(block.timestamp >= eventTime, "Festaking: bad timing for the request");
        _;
    }

    modifier _before(uint256 eventTime) {
        require(block.timestamp < eventTime, "Festaking: bad timing for the request");
        _;
    }

    function stake(uint256 amount) public returns (bool) {
        address sender = msg.sender;
        return _stakeToken(sender, amount);
    }

    function _stakeToken(address stakerAddr, uint256 amount)
        public
        _after(stakingStarts)
        _before(stakingEnds)
        returns (bool)
    {
        uint256 remainingToken = amount;

/* Change#1: 
         --> 1. Add Condition (stakingTotal > 0)
         --> 2. Instead of stakingTotal - remainingToken
               the condition should be (stakingTotal - stakedBalance) 
         --> And in the expression, (stakingToken - remainingToken) should be Replaced by this: (stakingTotal - stakedBalance)       
        
        if(remainingToken > (stakingTotal - remainingToken)){     // stakingTotal = It represents the total staking cap { stakingCap }
            remainingToken = (stakingTotal - remainingToken);    // Then stake the whatever available stakes are there
        }
*/

        // Change#2:
        uint256 _stakedBalance = stakedBalance;
       
        if (stakingTotal > 0 && remainingToken > (stakingTotal - _stakedBalance)) {
            // stakingTotal = It represents the total staking cap { stakingCap }
            remainingToken = (stakingTotal - _stakedBalance); // Then stake the whatever available stakes are there
        }

        // These requires are not necessary, because it will never happen, but won't hurt to double check
        // this is because stakedTotal and stakedBalance are only modified in this method during the staking period

        require(remainingToken > 0, "Festaking: Staking cap is filled"); // If no staking available then stop the staking!

        // The token that are being staked + total tokens already staked should be < = total available staking
        require(
            (remainingToken + stakedTotal) <= stakingTotal,
            "Festaking: this will increase staking amount pass the cap"
        );

        // Change#4 (a): Add tokenAddress and pass it to PayMe
        if (!_payMe(stakerAddr, remainingToken, stakeTokenAddress)) {
            return false;
        }
        emit Staked(stakeTokenAddress, stakerAddr, amount, remainingToken);

        if (remainingToken < amount) {
            // Return the unstaked amount to sender (from allowance)
            uint256 refund = amount - remainingToken;
            // pay/refund remaining funds

            // Change#4 (b): Add tokenAddress and pass it to PayTo
            if (_payTo(stakerAddr, stakerAddr, refund, stakeTokenAddress)) {
                emit Refunded(stakeTokenAddress, stakerAddr, refund);
            }
        }
        // Change#3 : Add StakedBalance too.
        stakedBalance = stakedBalance + remainingToken;
       
        stakedTotal = stakedTotal + remainingToken;
        stakes[stakerAddr] = stakes[stakerAddr] + remainingToken;
        return true;
    }

    // Change#4 Add token (Address) as a parameter to verify if its a reward/stake token
    function _payMe(
        address payer,
        uint256 amount,
        address token
    ) private returns (bool) {
        return _payTo(payer, address(this), amount, token);
    }

    // Change#4 Add token (Address) as a parameter to verify if its a reward/stake token
    function _payTo(
        address allower,
        address receiver,
        uint256 amount,
        address token
    ) private returns (bool) {
        // Request to transfer amount from the contract to receiver.
        // contract does not own the funds, so the allower must have added allowance to the contract
        // Allower is the original owner.
        ERC20Interface = IERC20(token);
        return ERC20Interface.transferFrom(allower, receiver, amount);
    }

    // Change#4 Add token (Address) as a parameter to verify if its a reward/stake token
    function _payDirect(
        address to,
        uint256 amount,
        address token
    ) private returns (bool) {
        ERC20Interface = IERC20(token);
        return ERC20Interface.transfer(to, amount);
    }

    // Change#5: Add rewardToken variable to add reward
    function addReward(
        uint256 rewardAmount,
        uint256 withdrawableAmount
    ) public _before(withdrawStarts) returns (bool) {
        require(rewardAmount > 0, "Festaking: reward must be positive");
        // uint cannot be negative, hence redundant require statements.
        // require(withdrawableAmount >= 0, "Festaking: withdrawable amount cannot be negative");
        require(
            withdrawableAmount <= rewardAmount,
            "Festaking: withdrawable amount must be less than or equal to the reward amount"
        );
        address from = msg.sender;
        if (!_payMe(from, rewardAmount, rewardTokenAddress)) {
            return false;
        }

        totalReward = totalReward + rewardAmount;
        rewardBalance = totalReward;
        earlyWithdrawReward = earlyWithdrawReward + withdrawableAmount;
        return true;
    }

    function withdraw(
        uint256 amount
    ) public _after(withdrawStarts) returns (bool) {
        address from = msg.sender;
        require(amount <= stakes[from], "Festaking: not enough balance");
        if (block.timestamp < withdrawEnds) {
            return _withdrawEarly(from, amount);
        } else {
            return _withdrawAfterClose(from, amount);
        }
    }

    // Change#6 (a): Check rewardTokenAddress & stakeTokenAddress 
    function _withdrawEarly(address from, uint256 amount)
    private
    returns (bool) {
        // This is the formula to calculate reward:
        // r = (earlyWithdrawReward / stakedTotal) * (block.timestamp - stakingEnds) / (withdrawEnds - stakingEnds)
        // w = (1+r) * a
        uint256 denom = (withdrawEnds - stakingEnds) * (stakedTotal);
        uint256 reward = (
        ( (block.timestamp - stakingEnds) *(earlyWithdrawReward) ) * (amount)
        ) / (denom);

       // Change# 7: Check if tokens are same for both reward & stake then 

        if (rewardTokenAddress == stakeTokenAddress) {
            uint256 payOut = amount + reward;
            // Change#4 (d): Add reward token (Address) and pass it to PayDirect
            bool principalAndRewardPaid = _payDirect(from, payOut, rewardTokenAddress);
            require(principalAndRewardPaid, "Festaking: error paying");

            emit PaidOut(stakeTokenAddress, rewardTokenAddress, from, amount, reward);    
        } 
        else {
            // Otherwise Add withdrawal for both tokens incase of LP Staking
            bool principalPaid = _payDirect(from, amount, stakeTokenAddress);
            bool rewardPaid = _payDirect(from, reward, rewardTokenAddress);
            require(principalPaid && rewardPaid, "Festaking: error paying");

            emit PaidOut(stakeTokenAddress, rewardTokenAddress, from, amount, reward);
        }

        rewardBalance = rewardBalance - reward;
        stakedBalance = stakedBalance - amount;
        stakes[from] = stakes[from] - amount;
        return true;
    }
// Change#6(b): Check rewardTokenAddress & stakeTokenAddress 
    function _withdrawAfterClose(address from, uint256 amount)
    private
    returns (bool) {
        uint256 reward = (rewardBalance * amount) / (stakedBalance);

       // Change# 7 (a): Check if tokens are same for both reward & stake then 

        if (rewardTokenAddress == stakeTokenAddress) {
            uint256 payOut = amount + reward;
            // Change#4 (d): Add reward token (Address) and pass it to PayDirect
            bool principalAndRewardPaid = _payDirect(from, payOut, rewardTokenAddress);
            require(principalAndRewardPaid, "Festaking: error paying");

            emit PaidOut(stakeTokenAddress, rewardTokenAddress, from, amount, reward);    
        } 
        else {
            // Otherwise Add withdrawal for both tokens incase of LP Staking
            bool principalPaid = _payDirect(from, amount, stakeTokenAddress);
            bool rewardPaid = _payDirect(from, reward, rewardTokenAddress);
            require(principalPaid && rewardPaid, "Festaking: error paying");

            emit PaidOut(stakeTokenAddress, rewardTokenAddress, from, amount, reward);
        }

        rewardBalance = rewardBalance - reward;
        stakedBalance = stakedBalance - amount;
        stakes[from] = stakes[from] - amount;
        return true;
    }

/* NOT NEEDED, if token address follows openzepellin ERC20 standard

1. This check is already performed in ERC20 contract
    modifier _hasEnoughToken(address staker, uint256 amount) {
        ERC20Interface = IERC20(tokenAddress);
        uint256 ourAllowance = ERC20Interface.allowance(staker, address(this));
        require(amount <= ourAllowance, "Festaking: Make sure to add enough allowance");
        _;
    }

2. This check is already performed in ERC20 contract
    modifier _hasAllowance(address allower, uint256 amount) {
        // Make sure the allower has provided the right allowance.
        ERC20Interface = IERC20(tokenAddress);
        uint256 ourAllowance = ERC20Interface.allowance(allower, address(this));
        require(amount <= ourAllowance, "Festaking: Make sure to add enough allowance");
        _;

*/

}