from pyteal import *

def approval_program():
    
    # Global States
    staking_token = Bytes("staking_token")
    reward_token = Bytes("reward_token")
    total_supply = Bytes("total_supply")
    staking_starts = Bytes("staking_starts")
    staking_ends = Bytes("staking_ends")
    staking_total = Bytes("staking_total")
    staked_total = Bytes("staked_total")
    withdraw_starts = Bytes("withdraw_starts")
    withdraw_ends = Bytes("withdraw_ends")
    total_rewards = Bytes("total_rewards")
    early_withdraw_rewards = Bytes("early_withdraw_rewards")
    reward_balance = Bytes("reward_balance")
    staked_balance = Bytes("staked_balance")
    application_admin = Bytes("application_admin")

    # Local States
    stakes = Bytes("stakes")

    # Helper Functions
    @Subroutine(TealType.bytes)
    def convert_uint_to_bytes(arg):
        string = ScratchVar(TealType.bytes)
        num = ScratchVar(TealType.uint64)
        digit = ScratchVar(TealType.uint64)
        return If(
            arg == Int(0),
            Bytes("0"),
            Seq([
                string.store(Bytes("")),
                For(num.store(arg), num.load() > Int(0), num.store(num.load() / Int(10))).Do(
                    Seq([
                        digit.store(num.load() % Int(10)),
                        string.store(
                            Concat(
                                Substring(
                                    Bytes('0123456789'),
                                    digit.load(),
                                    digit.load() + Int(1)
                                ),
                                string.load()
                            )
                        )
                    ])
                ),
                string.load()
            ])
        )

    # Log Events
    @Subroutine(TealType.none)
    def staked(token: TealType. uint64, requested_amount: TealType.uint64, staked_amount: TealType.uint64):
        return Log(Concat(Bytes("staked { token: "), convert_uint_to_bytes(token), Bytes(", requested_amount: "), convert_uint_to_bytes(requested_amount), Bytes(", staked_amount: "), convert_uint_to_bytes(staked_amount), Bytes("}") ))

    @Subroutine(TealType.none)
    def paid_out(stake: TealType. uint64, reward: TealType. uint64, amount: TealType.uint64, rewardAmt: TealType. uint64):
        return Log(Concat(Bytes("paid_out { token: "), convert_uint_to_bytes(stake), convert_uint_to_bytes(reward), Bytes(", amount: "), convert_uint_to_bytes(amount), Bytes(", reward: "), convert_uint_to_bytes(rewardAmt), Bytes("}") ))

    @Subroutine(TealType.none)
    def refunded(token: TealType. uint64, amount: TealType.uint64):
        return Log(Concat(Bytes("refunded { token: "), convert_uint_to_bytes(token), Bytes(", amount: "), convert_uint_to_bytes(amount), Bytes("}") ))

    # Modifier Functions
    @Subroutine(TealType.none)
    def positive(amount: TealType.uint64):
        return Assert(amount > Int(0))

    @Subroutine(TealType.none)
    def after(event_time: TealType.uint64):
        return Assert(Global.latest_timestamp() >= event_time)

    @Subroutine(TealType.none)
    def before(event_time: TealType.uint64):
        return Assert(Global.latest_timestamp() < event_time)

    @Subroutine(TealType.none)
    def real_address(address: TealType.bytes):
        return Assert(address != Global.zero_address())

    # Functions
    @Subroutine(TealType.none)
    def execute_asset_transfer(token: TealType.uint64, token_amount: TealType.uint64, token_receiver: TealType.bytes) -> Expr:
        return Seq([
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: token,
                TxnField.asset_amount: token_amount,
                TxnField.asset_receiver: token_receiver,
                TxnField.fee: Int(0),
                }),
            InnerTxnBuilder.Submit()
        ])

    @Subroutine(TealType.none)
    def is_asset_transfered(asset_id: TealType.uint64, amount: TealType.uint64) -> Expr:
        return Assert(
            And(
                Global.group_size() == Int(2),
                Gtxn[0].type_enum() == TxnType.AssetTransfer,
                Gtxn[0].xfer_asset() == asset_id,
                Gtxn[0].sender() == Txn.sender(),
                Gtxn[0].asset_receiver() == Global.current_application_address(),
                Gtxn[0].asset_amount() == amount,
                )
        )

    @Subroutine(TealType.none)
    def stake_token(amount: TealType.uint64):
        remaining_token = ScratchVar(TealType.uint64)
        return Seq([
            after(App.globalGet(staking_starts)),
            before(App.globalGet(staking_ends)),
            positive(amount),
            # Verify that staker has transfered assets to the application
            is_asset_transfered(App.globalGet(staking_token), amount),

            # If the amount to be staked is > total staking cap
            If(amount > (App.globalGet(staking_total) - App.globalGet(staked_balance)),
                remaining_token.store(App.globalGet(staking_total) - App.globalGet(staked_balance)),
                remaining_token.store(amount)
            ),

            # Exception('Festaking: Staking cap is filled')
            Assert(remaining_token.load() > Int(0)),

            # Exception('Festaking: this will increase staking amount pass the cap')
            Assert((remaining_token.load() + App.globalGet(staked_total)) <= App.globalGet(staking_total)),

            If(remaining_token.load() < amount,
                Seq([
                    execute_asset_transfer(App.globalGet(staking_token), amount - remaining_token.load(), Txn.sender()),
                    refunded(App.globalGet(staking_token), amount - remaining_token.load()),
                ])
            ),

            App.globalPut(staked_total, (App.globalGet(staked_total) + remaining_token.load())),
            App.globalPut(staked_balance, (App.globalGet(staked_balance) + remaining_token.load())),
            App.localPut(Txn.sender(), stakes, App.localGet(Txn.sender(), stakes) + remaining_token.load()),

            staked(App.globalGet(staking_token), amount, remaining_token.load()),

        ])

    @Subroutine(TealType.none)
    def withdraw_early(from_address: TealType.bytes, amount: TealType.uint64):
        # Scratch Variables
        denom = ScratchVar(TealType.uint64)
        reward = ScratchVar(TealType.uint64)
        pay_out = ScratchVar(TealType.uint64)
        return Seq([
            # This is the formula to calculate reward:
            # r = (earlyWithdrawReward / stakedTotal) * (block.timestamp - stakingEnds) / (withdrawEnds - stakingEnds)
            # w = (1+r) * a
            denom.store((App.globalGet(withdraw_ends) - App.globalGet(staking_ends)) * App.globalGet(staked_total)),
            reward.store(((Global.latest_timestamp() - App.globalGet(staking_ends)) * App.globalGet(early_withdraw_rewards) * amount) / denom.load()),
            
            # Add Condition to Check if its Traditional/LP Staking 
            If(App.globalGet(staking_token) == App.globalGet(reward_token))
                .Then(
                    Seq([
                        pay_out.store(amount + reward.load()),
                        # Transfer tokens to the withdrawer
                        execute_asset_transfer(App.globalGet(staking_token), pay_out.load(), from_address),
                        paid_out(App.globalGet(staking_token), App.globalGet(reward_token), amount, reward.load()),
                    ])
                )
                .Else(
                    Seq([
                        # Transfer stake & reward tokens to the withdrawer
                        execute_asset_transfer(App.globalGet(staking_token), amount, from_address),
                        execute_asset_transfer(App.globalGet(reward_token), reward.load(), from_address),
                        paid_out(App.globalGet(staking_token), App.globalGet(reward_token), amount, reward.load()),
                    ])
                ),
            
            App.globalPut(reward_balance, App.globalGet(reward_balance) - reward.load()),
            App.globalPut(staked_balance, App.globalGet(staked_balance) - amount),
            App.localPut(from_address, stakes, App.localGet(from_address, stakes) - amount),
        ])

    @Subroutine(TealType.none)
    def withdraw_after_close(from_address: TealType.bytes, amount: TealType.uint64):
        # Scratch Variables
        reward = ScratchVar(TealType.uint64)
        pay_out = ScratchVar(TealType.uint64)
        return Seq([
            reward.store((App.globalGet(reward_balance) * amount) / App.globalGet(staked_balance)),

            # Add Condition to Check if its Traditional/LP Staking 
            If(App.globalGet(staking_token) == App.globalGet(reward_token))
                .Then(
                    Seq([
                        pay_out.store(amount + reward.load()),
                        # Transfer tokens to the withdrawer
                        execute_asset_transfer(App.globalGet(staking_token), pay_out.load(), from_address),
                         paid_out(App.globalGet(staking_token), App.globalGet(reward_token), amount, reward.load()),
                    ])
                )
                .Else(
                    Seq([
                        # Transfer stake & reward tokens to the withdrawer
                        execute_asset_transfer(App.globalGet(staking_token), amount, from_address),
                        execute_asset_transfer(App.globalGet(reward_token), reward.load(), from_address),
                         paid_out(App.globalGet(staking_token), App.globalGet(reward_token), amount, reward.load()),
                    ])
                ),

            App.globalPut(reward_balance, App.globalGet(reward_balance) - reward.load()),
            App.globalPut(staked_balance, App.globalGet(staked_balance) - amount),
            App.localPut(from_address, stakes, App.localGet(from_address, stakes) - amount),
        ])

    @Subroutine(TealType.none)
    def withdraw(from_address: TealType.bytes, amount: TealType.uint64):
        return Seq([
            after(App.globalGet(withdraw_starts)),

            # Exception ("Festaking: not enough balance"),
            Assert(amount <= App.localGet(from_address, stakes)),

            If(Global.latest_timestamp() < App.globalGet(withdraw_ends),
                withdraw_early(from_address, amount),
                withdraw_after_close(from_address, amount)
            )
        ])

    @Subroutine(TealType.none)
    def add_reward(reward_amount: TealType.uint64, withdrawable_amount: TealType.uint64):
        return Seq([
            before(App.globalGet(withdraw_starts)),

            # Exception ("Festaking: reward must be positive"),
            Assert(reward_amount > Int(0)),

            # Exception ("withdrawable amount cannot be negative"),
            Assert(withdrawable_amount >= Int(0)),
            
            # Exception ("Festaking: withdrawable amount must be less than or equal to the reward amount"),
            Assert(withdrawable_amount <= reward_amount),

            # verifying that the sender has transfered the assets to the application
            is_asset_transfered(App.globalGet(reward_token), reward_amount),

            App.globalPut(total_rewards, App.globalGet(total_rewards) + reward_amount),
            App.globalPut(reward_balance, App.globalGet(total_rewards)),
            App.globalPut(early_withdraw_rewards, App.globalGet(early_withdraw_rewards) + withdrawable_amount),
        ])

    is_application_admin = Assert(Txn.sender() == App.globalGet(application_admin))

    # CONSTRUCTOR
    
    _staking_token = Btoi(Txn.application_args[0])
    _reward_token = Btoi(Txn.application_args[1])
    _staking_starts = Btoi(Txn.application_args[2])
    _staking_ends = Btoi(Txn.application_args[3])
    _withdraw_starts = Btoi(Txn.application_args[4])
    _withdraw_ends = Btoi(Txn.application_args[5])
    _staking_total = Btoi(Txn.application_args[6])
    _total_supply = Btoi(Txn.application_args[7])

    on_creation = Seq([
        Assert(Global.group_size() == Int(1)),
        App.globalPut(staking_token, _staking_token),
        App.globalPut(reward_token, _reward_token),
        App.globalPut(application_admin, Txn.sender()),

        # Exception('Festaking: zero staking start time'),
        Assert(_staking_starts > Int(0)),
        If(_staking_starts < Global.latest_timestamp(),
            App.globalPut(staking_starts, Global.latest_timestamp()),
            App.globalPut(staking_starts, _staking_starts)
        ),

        # Exception ('Festaking: staking end must be after staking starts'),
        Assert(_staking_ends > _staking_starts),
        App.globalPut(staking_ends, _staking_ends),

        # Exception ('Festaking: withdrawStarts must be after staking ends'),
        Assert(_withdraw_starts >= _staking_ends),
        App.globalPut(withdraw_starts, _withdraw_starts),

        # Exception ('Festaking: withdrawEnds must be after withdraw starts')
        Assert(_withdraw_ends >= _withdraw_starts),
        App.globalPut(withdraw_ends, _withdraw_ends),

        # Exception ('Festaking: stakingTotal must be positive'),
        Assert(_staking_total > Int(0)),
        App.globalPut(staking_total, _staking_total),

        App.globalPut(total_supply, _total_supply),
        Approve(),
    ])

    # Method SETUP
    on_setup = Seq(
        is_application_admin,
        # OPT-IN to Token from Application. 
        execute_asset_transfer(App.globalGet(staking_token), Int(0), Global.current_application_address()),
        # OPT-IN to Reward Token from Application.
        execute_asset_transfer(App.globalGet(reward_token), Int(0), Global.current_application_address()),
        Approve(),
    )

    # Method CHANGE_ADMIN
    _new_admin = Txn.application_args[1]
    on_change_admin = Seq([
        is_application_admin,
        real_address(_new_admin),
        App.globalPut(application_admin, _new_admin),
        Approve(),
    ])

    _amount = Btoi(Txn.application_args[1])

    # Method STAKE
    on_stake = Seq([
        stake_token(_amount),
        Approve(),
    ])

    # Method WITHDRAW
    on_withdraw = Seq([
        withdraw(Txn.sender(), _amount),
        Approve(),
    ])

    # Method ADD_REWARD
    _reward_amount = Btoi(Txn.application_args[1])
    _withdrawable_amount = Btoi(Txn.application_args[2])
    on_add_reward = Seq([
        is_application_admin,
        add_reward(_reward_amount, _withdrawable_amount),
        Approve(),
    ])

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("stake"), on_stake],
        [on_call_method == Bytes("withdraw"), on_withdraw],
        [on_call_method == Bytes("add_reward"), on_add_reward],
        [on_call_method == Bytes("change_admin"), on_change_admin],
    )

    on_delete = Seq([ 
        is_application_admin,
        Approve(),
    ])
    on_update = Seq([ 
        is_application_admin,
        Approve(),
    ])
    program = Cond(
        # Application Creation Call would be routed here.
        [Txn.application_id() == Int(0), on_creation],

        # All General Application calls will be routed here.
        [Txn.on_completion() == OnComplete.NoOp, on_call],
        # Reject DELETE and UPDATE Application Calls.
        [Txn.on_completion() == OnComplete.DeleteApplication, on_delete],
        [Txn.on_completion() == OnComplete.UpdateApplication, on_update],
        #
        # Users should OPT-IN to Application to allow Application to use LocalStorage of the user.
        [
            Or(
                Txn.on_completion() == OnComplete.CloseOut,
                Txn.on_completion() == OnComplete.OptIn,
            ),
            Approve(),
        ],
    )

    return compileTeal(program, Mode.Application, version=5)

print(approval_program())